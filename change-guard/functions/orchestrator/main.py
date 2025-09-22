import functions_framework
import json
import requests
from google.cloud import firestore

# Initialize Firestore
db = firestore.Client()

@functions_framework.http
def handler(request):
    """
    Minimal orchestrator that just initiates the process and tracks status.
    """
    request_json = request.get_json(silent=True)
    if not request_json or "commit_sha" not in request_json:
        return "ERROR: Missing 'commit_sha' in request body.", 400
    
    commit_sha = request_json["commit_sha"]
    repo_name = request_json.get("repo_name", "pranjalwagh/spring-petclinic")
    
    print(f"Starting analysis for commit {commit_sha} in {repo_name}")
    
    # Create initial record in Firestore
    db.collection("analysis_results").document(commit_sha).set({
        "commit_sha": commit_sha,
        "repo_name": repo_name,
        "status": "Downloading",
        "atomic_changes": [],
        "impacted_components": {"direct": [], "transitive": []}
    })
    
    # Trigger the downloader function
    project_id = request_json.get("project_id") or "noble-cocoa-471417-k3"
    region = request_json.get("region") or "asia-south1"
    downloader_url = f"https://{region}-{project_id}.cloudfunctions.net/downloader-function"
    
    try:
        requests.post(downloader_url, json={
            "commit_sha": commit_sha,
            "repo_name": repo_name,
            "project_id": project_id,
            "region": region
        }, timeout=30)
        return json.dumps({"status": "success", "message": "Analysis pipeline started"}), 200
    except Exception as e:
        print(f"Error starting analysis: {str(e)}")
        db.collection("analysis_results").document(commit_sha).update({
            "status": "Failed",
            "error": f"Failed to start analysis: {str(e)}"
        })
        return json.dumps({"status": "error", "message": str(e)}), 500