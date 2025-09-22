import functions_framework
import os
import json
import requests
import tempfile
import zipfile
import gc
import time
from google.cloud import firestore
from google.cloud import storage

# Initialize clients
db = firestore.Client()
storage_client = storage.Client()

@functions_framework.http
def handler(request):
    """
    Downloads the repository for a specific commit and saves it to Cloud Storage.
    Then triggers the next function in the pipeline.
    """
    request_json = request.get_json(silent=True)
    if not request_json or "commit_sha" not in request_json:
        return "ERROR: Missing required parameters.", 400
    
    commit_sha = request_json["commit_sha"]
    repo_name = request_json.get("repo_name", "pranjalwagh/spring-petclinic")
    project_id = request_json.get("project_id", "noble-cocoa-471417-k3")
    region = request_json.get("region", "asia-south1")
    
    print(f"Downloading repository {repo_name} at commit {commit_sha}")
    
    # Update status
    db.collection("analysis_results").document(commit_sha).update({
        "status": "Downloading repository"
    })
    
    bucket_name = "noble-cocoa-471417-k3.firebasestorage.app"
    bucket = storage_client.bucket(bucket_name)
    
    try:
        # Create a temp directory for download
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download the repository
            zip_file_path = os.path.join(temp_dir, "repo.zip")
            zip_url = f"https://github.com/{repo_name}/archive/{commit_sha}.zip"
            
            with requests.get(zip_url, stream=True) as response:
                response.raise_for_status()
                with open(zip_file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
            
            # Get info about changed files
            owner, repo = repo_name.split('/')
            github_api_url = f"https://api.github.com/repos/{owner}/{repo}"
            
            # Get the changes
            changed_files = get_changed_files(commit_sha, github_api_url)
            
            if not changed_files:
                # No Java files changed, complete the analysis
                db.collection("analysis_results").document(commit_sha).update({
                    "status": "Completed",
                    "message": "No Java files changed"
                })
                return "No Java files changed", 200
            
            # Save changed files data to Firestore
            db.collection("analysis_data").document(commit_sha).set({
                "changed_files": changed_files
            })
            
            # Upload repo zip to storage
            blob = bucket.blob(f"repos/{commit_sha}/repo.zip")
            blob.upload_from_filename(zip_file_path)
            
            # Trigger the impact analyzer function
            impact_analyzer_url = f"https://{region}-{project_id}.cloudfunctions.net/impact-analyzer-function"
            
            requests.post(impact_analyzer_url, json={
                "commit_sha": commit_sha,
                "repo_name": repo_name,
                "project_id": project_id,
                "region": region
            }, timeout=30)
            
            return "Repository downloaded and next step triggered", 200
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error in downloader: {str(e)}")
        db.collection("analysis_results").document(commit_sha).update({
            "status": "Failed",
            "error": f"Download failed: {str(e)}"
        })
        return f"Error: {str(e)}", 500

def get_changed_files(commit_sha, github_api_url):
    """
    Gets a list of Java files that changed in this commit.
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    # Get the commit
    commit_url = f"{github_api_url}/commits/{commit_sha}"
    commit_response = requests.get(commit_url, headers=headers)
    commit_response.raise_for_status()
    commit_data = commit_response.json()
    
    if not commit_data.get("parents"):
        return []
    
    parent_sha = commit_data["parents"][0]["sha"]
    
    # Get the comparison
    compare_url = f"{github_api_url}/compare/{parent_sha}...{commit_sha}"
    compare_response = requests.get(compare_url, headers=headers)
    compare_response.raise_for_status()
    compare_data = compare_response.json()
    
    # Filter for Java files
    java_files = [
        {
            "filename": f["filename"],
            "parent_sha": parent_sha,
            "commit_sha": commit_sha
        }
        for f in compare_data.get("files", [])
        if f["filename"].endswith(".java")
    ]
    
    return java_files