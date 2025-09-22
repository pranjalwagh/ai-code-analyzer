import functions_framework
import os
import json
import requests
import base64
import tempfile
import zipfile
import io
import javalang
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# --- Configuration ---
REPO_OWNER = "pranjalwagh"
REPO_NAME = "spring-petclinic"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
DB = firestore.Client()

# --- Add these lines ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"
# --- End of section to add ---

# --- Main Handler ---
@functions_framework.http
def handler(request):
    """
    Orchestrates a full analysis for a specific commit:
    1. Downloads a snapshot of the repo at that commit.
    2. Builds and stores a dependency graph for that snapshot.
    3. Analyzes the changes against the new graph.
    4. Saves the final result.
    """
    request_json = request.get_json(silent=True)
    if not request_json or "commit_sha" not in request_json:
        return "ERROR: Missing 'commit_sha' in request body.", 400
    
    # ISSUE 1: repo_name is not being extracted from the request
    commit_sha = request_json["commit_sha"]
    # ADD THIS LINE:
    repo_name = request_json.get("repo_name", "pranjalwagh/spring-petclinic")
    
    print(f"--- Starting full analysis for commit: {commit_sha} ---")
    print(f"--- Repository: {repo_name} ---")

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # --- Step 1: Download and extract repo snapshot at the specific commit ---
            print(f"Downloading repo snapshot for commit {commit_sha}...")
            
            # ISSUE 2: GITHUB_API_URL is undefined, causing the None URL error
            # REPLACE THIS LINE:
            # zip_url = f"{GITHUB_API_URL}/zipball/{commit_sha}"
            # WITH THIS:
            zip_url = f"https://github.com/{repo_name}/archive/{commit_sha}.zip"
            
            zip_response = requests.get(zip_url, stream=True)
            zip_response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(zip_response.content)) as z:
                z.extractall(temp_dir)
            
            # The extracted folder has a generated name, find it
            repo_root_dir = os.path.join(temp_dir, os.listdir(temp_dir)[0])
            print(f"Repository extracted to: {repo_root_dir}")

            # --- Step 2: Build and store the dependency graph for this commit ---
            print(f"Building and storing dependency graph for commit {commit_sha}...")
            build_and_store_graph_for_commit(repo_root_dir, commit_sha)

            # --- Step 3: Get the specific files that changed in this commit ---
            # ISSUE 3: This function may need the repo_name parameter
            changed_files = get_changed_files_from_api(commit_sha, repo_name)
            if not changed_files:
                # Still save a result so the frontend knows the analysis is done
                analysis_result = {"commit_sha": commit_sha, "status": "Completed", "atomic_changes": [], "impacted_components": {"direct": [], "transitive": []}}
                DB.collection("analysis_results").document(commit_sha).set(analysis_result)
                return f"Analysis complete for {commit_sha}: No Java files changed.", 200

            # --- Step 4: Call the parser for semantic diffing ---
            # ISSUE 4: Environment variables not set properly
            # REPLACE THIS LINE:
            # parser_function_url = os.environ.get("PARSER_FUNCTION_URL")
            # WITH THIS:
            project_id = os.environ.get('GCP_PROJECT', 'noble-cocoa-471417-k3')
            region = os.environ.get('GCP_REGION', 'asia-south1')
            parser_function_url = f"https://{region}-{project_id}.cloudfunctions.net/java-parser-function"
            print(f"Using parser URL: {parser_function_url}")
            
            atomic_changes = []
            for file_data in changed_files:
                response = requests.post(parser_function_url, json=file_data)
                response.raise_for_status()
                parsed_changes = response.json()
                if parsed_changes: atomic_changes.extend(parsed_changes)

            print(f"Identified Atomic Changes: {atomic_changes}")

            # --- Step 5: Find impact radius using the NEW commit-specific graph ---
            impacted_components = find_impact_radius(atomic_changes, commit_sha)
            print(f"Calculated Impact Radius: {impacted_components}")

            # --- Step 6: Assemble and save the initial result ---
            analysis_result = {
                "commit_sha": commit_sha,
                "atomic_changes": atomic_changes,
                "impacted_components": impacted_components,
                "status": "Processing"  # <-- STATUS CHANGED
            }
            doc_ref = DB.collection("analysis_results").document(commit_sha)
            doc_ref.set(analysis_result)
            print("Initial analysis result saved to Firestore.")

            # --- Step 7: Trigger the GenAI Augmenter ---
            # ISSUE 5: Environment variable not set properly
            # REPLACE THIS LINE:
            # gemini_function_url = os.environ.get("GEMINI_FUNCTION_URL")
            # WITH THIS:
            gemini_function_url = f"https://{region}-{project_id}.cloudfunctions.net/gemini-augmenter-function"
            print(f"Using Gemini URL: {gemini_function_url}")
            
            if gemini_function_url:
                print(f"Triggering Gemini Augmenter for commit {commit_sha}...")
                # This is a "fire-and-forget" call. We don't wait for the response.
                requests.post(gemini_function_url, json={"commit_sha": commit_sha})
            
            return json.dumps(analysis_result), 200, {'Content-Type': 'application/json'}

        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            error_result = {"commit_sha": commit_sha, "status": "Failed", "error": str(e)}
            DB.collection("analysis_results").document(commit_sha).set(error_result)
            # Re-raise the exception to return a 500 error
            raise e
def build_and_store_graph_for_commit(repo_path, commit_sha):
    """
    Parses all Java AND Frontend files to build a comprehensive dependency graph,
    including UI-to-API call mappings.
    """
    # We need to import the new parser inside the function
    import esprima

    batch = DB.batch()
    java_graph_ref = DB.collection("graph_snapshots").document(commit_sha).collection("graph")
    # --- NEW: A separate collection for UI component data ---
    ui_graph_ref = DB.collection("graph_snapshots").document(commit_sha).collection("ui_components")

    parsed_java_files = 0
    parsed_ui_files = 0
    
    frontend_extensions = ('.js', '.jsx', '.ts', '.tsx', '.html', '.vue')

    for root, _, files in os.walk(repo_path):
        for file in files:
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, repo_path).replace("\\", "/")

            # --- Logic for Java files (as before, but inside the new loop) ---
            if file.endswith(".java"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
                    tree = javalang.parse.parse(content)
                    package_name = tree.package.name if tree.package else ""
                    class_declarations = [c for c in tree.types if isinstance(c, javalang.tree.ClassDeclaration)]
                    if not class_declarations: continue
                    
                    main_class = class_declarations[0]
                    full_class_name = f"{package_name}.{main_class.name}"
                    
                    doc_data = {
                        "file_path": relative_path, "class_name": main_class.name, "package": package_name, 
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
                                "method_name": method_node.name, "http_method": http_method, "path": full_path
                            })
                    
                    doc_ref = java_graph_ref.document(full_class_name)
                    batch.set(doc_ref, doc_data)
                    parsed_java_files += 1
                except Exception as e:
                    print(f"  - Could not parse Java file {relative_path}. Error: {e}")

            # --- NEW: Logic to parse frontend files for API calls ---
            elif file.endswith(frontend_extensions):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
                    # A simple regex is often better for this than a full AST for an MVP
                    import re
                    # This regex looks for strings that look like API paths, e.g., fetch('/api/vets')
                    api_calls = re.findall(r"['\"](/[\w/.-]+)['\"]", content)
                    if api_calls:
                        safe_doc_id = relative_path.replace("/", "|")
                        doc_ref = ui_graph_ref.document(safe_doc_id)
                        batch.set(doc_ref, {"api_calls": list(set(api_calls))}) # Store unique API paths
                        parsed_ui_files += 1
                except Exception as e:
                    print(f"  - Could not parse UI file {relative_path}. Error: {e}")

    print(f"Parsed {parsed_java_files} Java files and {parsed_ui_files} UI files for graph.")
    batch.commit()
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

def get_changed_files_from_api(commit_sha):
    # This function is updated to pass the authentication headers.
    commit_url = f"{GITHUB_API_URL}/commits/{commit_sha}"
    commit_response = requests.get(commit_url, headers=HEADERS) # <-- ADDED HEADERS
    commit_response.raise_for_status()
    commit_data = commit_response.json()

    if not commit_data["parents"]: return []
    parent_sha = commit_data["parents"][0]["sha"]

    compare_url = f"{GITHUB_API_URL}/compare/{parent_sha}...{commit_sha}"
    compare_response = requests.get(compare_url, headers=HEADERS) # <-- ADDED HEADERS
    compare_response.raise_for_status()
    compare_data = compare_response.json()
    
    changed_files_list = []
    java_files = [f for f in compare_data.get("files", []) if f["filename"].endswith(".java")]

    for file_info in java_files:
        filename = file_info["filename"]
        before_res = requests.get(f"{GITHUB_API_URL}/contents/{filename}?ref={parent_sha}", headers=HEADERS) # <-- ADDED HEADERS
        before_content = base64.b64decode(before_res.json()["content"]).decode('utf-8') if before_res.status_code == 200 else ""
        after_res = requests.get(f"{GITHUB_API_URL}/contents/{filename}?ref={commit_sha}", headers=HEADERS) # <-- ADDED HEADERS
        after_content = base64.b64decode(after_res.json()["content"]).decode('utf-8') if after_res.status_code == 200 else ""
        changed_files_list.append({ "filename": filename, "before_content": before_content, "after_content": after_content })
        
    return changed_files_list

