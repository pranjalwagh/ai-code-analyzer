import functions_framework
import os
import json
import requests
import tempfile
import zipfile
import javalang
import base64
from google.cloud import firestore
from google.cloud import storage
from google.cloud.firestore_v1.base_query import FieldFilter

# Initialize clients
db = firestore.Client()
storage_client = storage.Client()

@functions_framework.http
def handler(request):
    """
    Analyzes repository code to build a dependency graph and determine impact radius.
    """
    request_json = request.get_json(silent=True)
    if not request_json or "commit_sha" not in request_json:
        return "ERROR: Missing required parameters.", 400
    
    commit_sha = request_json["commit_sha"]
    repo_name = request_json.get("repo_name", "pranjalwagh/spring-petclinic")
    project_id = request_json.get("project_id", "noble-cocoa-471417-k3")
    region = request_json.get("region", "asia-south1")
    
    print(f"Analyzing impact for commit {commit_sha}")
    
    # Update status
    db.collection("analysis_results").document(commit_sha).update({
        "status": "Building dependency graph"
    })
    
    bucket_name = "noble-cocoa-471417-k3.firebasestorage.app"
    bucket = storage_client.bucket(bucket_name)
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download the repository zip from Cloud Storage
            zip_path = os.path.join(temp_dir, "repo.zip")
            blob = bucket.blob(f"repos/{commit_sha}/repo.zip")
            blob.download_to_filename(zip_path)
            
            # Extract the repository
            extract_dir = os.path.join(temp_dir, "repo")
            os.makedirs(extract_dir, exist_ok=True)
            
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(extract_dir)
            
            # Find the repository root directory
            subdirs = [d for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
            if not subdirs:
                raise Exception("No repository directory found after extraction")
            
            repo_dir = os.path.join(extract_dir, subdirs[0])
            
            # Build dependency graph
            build_dependency_graph(repo_dir, commit_sha)
            
            # Get changed files data
            doc_ref = db.collection("analysis_data").document(commit_sha)
            doc = doc_ref.get()
            if not doc.exists:
                raise Exception("Changed files data not found")
            
            changed_files_data = doc.to_dict().get("changed_files", [])
            
            # Process changed files to get semantic changes
            atomic_changes = process_changed_files(changed_files_data, repo_name, commit_sha)
            
            # Find impact radius
            impacted_components = find_impact_radius(atomic_changes, commit_sha)
            
            # Update analysis results
            db.collection("analysis_results").document(commit_sha).update({
                "atomic_changes": atomic_changes,
                "impacted_components": impacted_components,
                "status": "Processing"
            })
            
            # Trigger the Gemini augmenter
            gemini_url = f"https://{region}-{project_id}.cloudfunctions.net/gemini-augmenter-function"
            
            requests.post(gemini_url, json={
                "commit_sha": commit_sha
            }, timeout=30)
            
            return "Impact analysis completed", 200
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in impact analyzer: {str(e)}")
        db.collection("analysis_results").document(commit_sha).update({
            "status": "Failed",
            "error": f"Impact analysis failed: {str(e)}"
        })
        return f"Error: {str(e)}", 500

def build_dependency_graph(repo_path, commit_sha):
    """
    Builds a dependency graph for the repository and stores it in Firestore.
    """
    graph_ref = db.collection("graph_snapshots").document(commit_sha).collection("graph")
    
    batch_size = 20
    current_batch = db.batch()
    docs_in_batch = 0
    
    for root, _, files in os.walk(repo_path):
        for file in files:
            if not file.endswith(".java"):
                continue
                
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, repo_path).replace("\\", "/")
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = javalang.parse.parse(content)
                package_name = tree.package.name if tree.package else ""
                class_declarations = [c for c in tree.types if isinstance(c, javalang.tree.ClassDeclaration)]
                
                if not class_declarations:
                    continue
                
                main_class = class_declarations[0]
                full_class_name = f"{package_name}.{main_class.name}"
                
                doc_data = {
                    "file_path": relative_path,
                    "class_name": main_class.name,
                    "package": package_name,
                    "imports": [imp.path for imp in tree.imports],
                    "methods": [method.name for _, method in main_class.filter(javalang.tree.MethodDeclaration)],
                    "api_endpoints": []
                }
                
                # Extract API endpoints
                base_path = ""
                for annotation in main_class.annotations:
                    if annotation.name == 'RequestMapping' and hasattr(annotation, 'element') and annotation.element:
                        if isinstance(annotation.element, javalang.tree.Literal):
                            base_path = annotation.element.value.strip('"')
                
                for _, method_node in main_class.filter(javalang.tree.MethodDeclaration):
                    http_method, path = None, ""
                    for ann in method_node.annotations:
                        if ann.name in ['GetMapping', 'PostMapping', 'PutMapping', 'DeleteMapping']:
                            http_method = ann.name.replace('Mapping', '').upper()
                            if hasattr(ann, 'element') and ann.element and isinstance(ann.element, javalang.tree.Literal):
                                path = ann.element.value.strip('"')
                    if http_method:
                        full_path = os.path.join(base_path, path).replace("\\", "/")
                        doc_data["api_endpoints"].append({
                            "method_name": method_node.name,
                            "http_method": http_method,
                            "path": full_path
                        })
                
                doc_ref = graph_ref.document(full_class_name)
                current_batch.set(doc_ref, doc_data)
                docs_in_batch += 1
                
                if docs_in_batch >= batch_size:
                    current_batch.commit()
                    current_batch = db.batch()
                    docs_in_batch = 0
                
            except Exception as e:
                print(f"Error parsing file {relative_path}: {str(e)}")
    
    # Commit any remaining documents
    if docs_in_batch > 0:
        current_batch.commit()
    
    print(f"Dependency graph for commit {commit_sha} built successfully")

def process_changed_files(changed_files, repo_name, commit_sha):
    """
    Process the changed files to extract atomic changes (semantic diff).
    """
    owner, repo = repo_name.split('/')
    github_api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    atomic_changes = []
    
    for file_info in changed_files:
        filename = file_info["filename"]
        parent_sha = file_info["parent_sha"]
        
        # Get file content before and after
        before_url = f"{github_api_url}/contents/{filename}?ref={parent_sha}"
        after_url = f"{github_api_url}/contents/{filename}?ref={commit_sha}"
        
        try:
            before_res = requests.get(before_url, headers=headers)
            before_content = ""
            if before_res.status_code == 200:
                before_content = base64.b64decode(before_res.json()["content"]).decode('utf-8')
            
            after_res = requests.get(after_url, headers=headers)
            after_content = ""
            if after_res.status_code == 200:
                after_content = base64.b64decode(after_res.json()["content"]).decode('utf-8')
            
            # Compare file contents
            changes = compare_java_files(filename, before_content, after_content)
            if changes:
                atomic_changes.extend(changes)
                
        except Exception as e:
            print(f"Error processing file {filename}: {str(e)}")
    
    return atomic_changes

# In impact_analyzer/main.py, replace the compare_java_files function with:

def compare_java_files(filename, before_content, after_content):
    """
    Call the java-parser function to analyze changes.
    """
    project_id = os.environ.get('GCP_PROJECT', 'noble-cocoa-471417-k3')
    region = os.environ.get('GCP_REGION', 'asia-south1')
    parser_url = f"https://{region}-{project_id}.cloudfunctions.net/java-parser-function"
    
    try:
        response = requests.post(parser_url, json={
            "filename": filename,
            "before_content": before_content,
            "after_content": after_content
        })
        response.raise_for_status()
        parsed_changes = response.json()
        return parsed_changes
    except Exception as e:
        print(f"Error calling java-parser for file {filename}: {str(e)}")
        # Return a basic change notification if parser fails
        return [{
            "file": filename,
            "type": "UKN",  # Unknown change type
            "details": f"Changed file: {filename} (parser error)"
        }]

def find_impact_radius(atomic_changes, commit_sha):
    """
    Find the impact radius of the changes using the dependency graph.
    """
    if not atomic_changes:
        return {"direct": [], "transitive": []}
    
    graph_collection_ref = db.collection("graph_snapshots").document(commit_sha).collection("graph")
    changed_classes_full_names = set()
    
    for change in atomic_changes:
        docs = graph_collection_ref.where("file_path", "==", change["file"]).limit(1).stream()
        class_doc = next(docs, None)
        if class_doc:
            doc_dict = class_doc.to_dict()
            package = doc_dict.get('package', '')
            class_name = doc_dict.get('class_name', '')
            if package and class_name:
                full_class_name = f"{package}.{class_name}"
                changed_classes_full_names.add(full_class_name)
    
    if not changed_classes_full_names:
        return {"direct": [], "transitive": []}
    
    direct_dependents = set()
    for class_name in changed_classes_full_names:
        query = graph_collection_ref.where(filter=FieldFilter("imports", "array_contains", class_name))
        docs = query.stream()
        for doc in docs:
            if doc.id not in changed_classes_full_names:
                direct_dependents.add(doc.id)
    
    return {
        "direct": sorted(list(direct_dependents)),
        "transitive": []  # For a simple implementation, we're not calculating transitive impacts
    }