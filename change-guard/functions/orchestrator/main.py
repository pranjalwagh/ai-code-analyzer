import functions_framework
import os
import json
import requests
import base64
import tempfile
import zipfile
import io
import javalang
import gc  # Add garbage collection
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- Configuration ---
DB = firestore.Client()

# --- GitHub API Authentication ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# --- Main Handler ---
@functions_framework.http
def handler(request):
    """
    Memory-optimized orchestrator for analyzing code changes.
    """
    request_json = request.get_json(silent=True)
    if not request_json or "commit_sha" not in request_json:
        return "ERROR: Missing 'commit_sha' in request body.", 400
    
    commit_sha = request_json["commit_sha"]
    repo_name = request_json.get("repo_name", "pranjalwagh/spring-petclinic")
    
    print(f"--- Starting full analysis for commit: {commit_sha} ---")
    print(f"--- Repository: {repo_name} ---")

    # Initialize result in Firestore early to show processing status
    DB.collection("analysis_results").document(commit_sha).set({
        "commit_sha": commit_sha,
        "status": "Initializing",
        "repo_name": repo_name
    })

    try:
        # Define GitHub API URL based on repo_name
        owner, repo = repo_name.split('/')
        github_api_url = f"https://api.github.com/repos/{owner}/{repo}"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # --- Step 1: Download repository efficiently ---
            print(f"Downloading repo snapshot for commit {commit_sha}...")
            zip_file_path = os.path.join(temp_dir, "repo.zip")
            
            # Stream download to file instead of memory
            zip_url = f"https://github.com/{repo_name}/archive/{commit_sha}.zip"
            with requests.get(zip_url, stream=True) as response:
                response.raise_for_status()
                with open(zip_file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
            
            # Extract files
            with zipfile.ZipFile(zip_file_path) as z:
                z.extractall(temp_dir)
            
            # Free up memory by removing the zip file
            os.remove(zip_file_path)
            gc.collect()  # Force garbage collection
            
            # Find repository root directory
            subdirs = [d for d in os.listdir(temp_dir) if os.path.isdir(os.path.join(temp_dir, d))]
            if not subdirs:
                raise Exception("No directories found after extraction")
            
            repo_root_dir = os.path.join(temp_dir, subdirs[0])
            print(f"Repository extracted to: {repo_root_dir}")

            # Update status in Firestore
            DB.collection("analysis_results").document(commit_sha).update({
                "status": "Building dependency graph"
            })

            # --- Step 2: Build dependency graph ---
            print(f"Building dependency graph for commit {commit_sha}...")
            build_and_store_graph_for_commit(repo_root_dir, commit_sha)
            gc.collect()  # Force garbage collection

            # --- Step 3: Get changed files ---
            print(f"Getting changed files for commit {commit_sha}...")
            DB.collection("analysis_results").document(commit_sha).update({
                "status": "Analyzing changes"
            })
            
            changed_files = get_changed_files_from_api(commit_sha, github_api_url, HEADERS)
            if not changed_files:
                # No Java files changed
                analysis_result = {
                    "commit_sha": commit_sha,
                    "status": "Completed", 
                    "atomic_changes": [], 
                    "impacted_components": {"direct": [], "transitive": []}
                }
                DB.collection("analysis_results").document(commit_sha).set(analysis_result)
                return f"Analysis complete for {commit_sha}: No Java files changed.", 200

            # --- Step 4: Process changes in batches ---
            project_id = os.environ.get('GCP_PROJECT', 'noble-cocoa-471417-k3')
            region = os.environ.get('GCP_REGION', 'asia-south1')
            parser_function_url = f"https://{region}-{project_id}.cloudfunctions.net/java-parser-function"
            
            print(f"Using parser URL: {parser_function_url}")
            atomic_changes = []
            
            # Process in smaller batches to reduce memory usage
            batch_size = 3
            for i in range(0, len(changed_files), batch_size):
                batch = changed_files[i:i+batch_size]
                for file_data in batch:
                    try:
                        response = requests.post(parser_function_url, json=file_data)
                        response.raise_for_status()
                        parsed_changes = response.json()
                        if parsed_changes: 
                            atomic_changes.extend(parsed_changes)
                    except Exception as e:
                        print(f"Error parsing file {file_data.get('filename')}: {str(e)}")
                
                # Force garbage collection after each batch
                gc.collect()

            print(f"Identified {len(atomic_changes)} atomic changes")

            # --- Step 5: Find impact radius ---
            print("Calculating impact radius...")
            impacted_components = find_impact_radius(atomic_changes, commit_sha)

            # --- Step 6: Save results ---
            analysis_result = {
                "commit_sha": commit_sha,
                "atomic_changes": atomic_changes,
                "impacted_components": impacted_components,
                "status": "Processing"
            }
            DB.collection("analysis_results").document(commit_sha).set(analysis_result)
            print("Analysis result saved to Firestore.")

            # --- Step 7: Trigger AI augmentation ---
            gemini_function_url = f"https://{region}-{project_id}.cloudfunctions.net/gemini-augmenter-function"
            print(f"Using Gemini URL: {gemini_function_url}")
            
            try:
                requests.post(gemini_function_url, json={"commit_sha": commit_sha}, timeout=5)
                print("Gemini augmenter triggered")
            except requests.exceptions.Timeout:
                print("Gemini augmenter triggered (timeout ignored)")
            except Exception as e:
                print(f"Error triggering Gemini augmenter: {str(e)}")
            
            return json.dumps(analysis_result), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        import traceback
        print(f"An unexpected error occurred: {str(e)}")
        traceback.print_exc()
        error_result = {"commit_sha": commit_sha, "status": "Failed", "error": str(e)}
        DB.collection("analysis_results").document(commit_sha).set(error_result)
        return json.dumps({"error": str(e)}), 500

def build_and_store_graph_for_commit(repo_path, commit_sha):
    """
    Memory-optimized version that processes files in smaller batches.
    """
    # We need to import the new parser inside the function
    import esprima

    java_graph_ref = DB.collection("graph_snapshots").document(commit_sha).collection("graph")
    ui_graph_ref = DB.collection("graph_snapshots").document(commit_sha).collection("ui_components")

    parsed_java_files = 0
    parsed_ui_files = 0
    
    frontend_extensions = ('.js', '.jsx', '.ts', '.tsx', '.html', '.vue')

    # Process in batches to reduce memory usage
    batch_size = 10
    current_batch = DB.batch()
    docs_in_batch = 0

    for root, _, files in os.walk(repo_path):
        for file in files:
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, repo_path).replace("\\", "/")

            # --- Logic for Java files ---
            if file.endswith(".java"):
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
                    
                    doc_ref = java_graph_ref.document(full_class_name)
                    current_batch.set(doc_ref, doc_data)
                    parsed_java_files += 1
                    docs_in_batch += 1
                    
                    # Commit batch when it reaches the batch size
                    if docs_in_batch >= batch_size:
                        current_batch.commit()
                        current_batch = DB.batch()
                        docs_in_batch = 0
                        # Force garbage collection
                        gc.collect()
                        
                except Exception as e:
                    print(f"  - Could not parse Java file {relative_path}. Error: {e}")

            # --- Logic for frontend files ---
            elif file.endswith(frontend_extensions):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f: 
                        content = f.read()
                    
                    import re
                    api_calls = re.findall(r"['\"](/[\w/.-]+)['\"]", content)
                    if api_calls:
                        safe_doc_id = relative_path.replace("/", "|")
                        doc_ref = ui_graph_ref.document(safe_doc_id)
                        current_batch.set(doc_ref, {"api_calls": list(set(api_calls))})
                        parsed_ui_files += 1
                        docs_in_batch += 1
                        
                        # Commit batch when it reaches the batch size
                        if docs_in_batch >= batch_size:
                            current_batch.commit()
                            current_batch = DB.batch()
                            docs_in_batch = 0
                            # Force garbage collection
                            gc.collect()
                            
                except Exception as e:
                    print(f"  - Could not parse UI file {relative_path}. Error: {e}")

    # Commit any remaining documents in the last batch
    if docs_in_batch > 0:
        current_batch.commit()

    print(f"Parsed {parsed_java_files} Java files and {parsed_ui_files} UI files for graph.")
    print(f"Graph for commit {commit_sha} stored successfully.")

def find_impact_radius(atomic_changes, commit_sha):
    """
    Finds downstream dependencies by querying the commit-specific graph.
    """
    if not atomic_changes: return {"direct": [], "transitive": []}

    graph_collection_ref = DB.collection("graph_snapshots").document(commit_sha).collection("graph")
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

    if not changed_classes_full_names: return {"direct": [], "transitive": []}
    
    direct_dependents = set()
    for class_name in changed_classes_full_names:
        query = graph_collection_ref.where(filter=FieldFilter("imports", "array_contains", class_name))
        docs = query.stream()
        for doc in docs:
            if doc.id not in changed_classes_full_names:
                 direct_dependents.add(doc.id)
    
    return {"direct": sorted(list(direct_dependents)), "transitive": []}

def get_changed_files_from_api(commit_sha, github_api_url, headers):
    """
    Get changed Java files between this commit and its parent.
    Updated to accept github_api_url and headers parameters.
    """
    commit_url = f"{github_api_url}/commits/{commit_sha}"
    commit_response = requests.get(commit_url, headers=headers)
    commit_response.raise_for_status()
    commit_data = commit_response.json()

    if not commit_data["parents"]: return []
    parent_sha = commit_data["parents"][0]["sha"]

    compare_url = f"{github_api_url}/compare/{parent_sha}...{commit_sha}"
    compare_response = requests.get(compare_url, headers=headers)
    compare_response.raise_for_status()
    compare_data = compare_response.json()
    
    changed_files_list = []
    java_files = [f for f in compare_data.get("files", []) if f["filename"].endswith(".java")]

    for file_info in java_files:
        filename = file_info["filename"]
        before_res = requests.get(f"{github_api_url}/contents/{filename}?ref={parent_sha}", headers=headers)
        before_content = base64.b64decode(before_res.json()["content"]).decode('utf-8') if before_res.status_code == 200 else ""
        
        after_res = requests.get(f"{github_api_url}/contents/{filename}?ref={commit_sha}", headers=headers)
        after_content = base64.b64decode(after_res.json()["content"]).decode('utf-8') if after_res.status_code == 200 else ""
        
        changed_files_list.append({
            "filename": filename, 
            "before_content": before_content, 
            "after_content": after_content
        })
        
    return changed_files_list
