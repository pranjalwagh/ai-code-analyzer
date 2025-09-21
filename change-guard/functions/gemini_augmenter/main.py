import functions_framework
import os
import json
import base64
import requests
from google.cloud import firestore
import vertexai
from vertexai.generative_models import GenerativeModel

# --- Configuration ---
GCP_PROJECT = os.environ.get("GCP_PROJECT")
GCP_REGION = os.environ.get("GCP_REGION")
MODEL_NAME = "gemini-1.5-flash-002"
DB = firestore.Client()
REPO_OWNER = "spring-projects"
REPO_NAME = "spring-petclinic"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# --- Initialization ---
try:
    vertexai.init(project=GCP_PROJECT, location=GCP_REGION)
    model = GenerativeModel(model_name=MODEL_NAME)
    print("Vertex AI initialized successfully.")
except Exception as e:
    print(f"Error initializing Vertex AI: {e}")
    model = None

# --- Main Handler ---
@functions_framework.http
def handler(request):
    """
    Receives a commit SHA, reads the analysis from Firestore, generates
    AI insights, and updates the Firestore document.
    """
    if not model:
        return "Vertex AI client not initialized. Check logs for errors.", 500

    request_json = request.get_json(silent=True)
    if not request_json or "commit_sha" not in request_json:
        return "ERROR: Missing 'commit_sha' in request body.", 400
    
    commit_sha = request_json["commit_sha"]
    print(f"--- Augmenting analysis for commit: {commit_sha} ---")

    try:
        doc_ref = DB.collection("analysis_results").document(commit_sha)
        doc = doc_ref.get()
        if not doc.exists:
            print(f"ERROR: Analysis document for commit {commit_sha} not found.")
            return f"Analysis document for {commit_sha} not found.", 404
        
        analysis_data = doc.to_dict()

        change_to_process = None
        for change in analysis_data.get("atomic_changes", []):
            if change["type"] in ["CM", "AM", "DC"]:
                change_to_process = change
                break
        
        if not change_to_process:
            print("No significant changes found to generate insights for.")
            doc_ref.update({"status": "Completed"})
            return "No significant changes to process.", 200

        summary = generate_summary(change_to_process, analysis_data, commit_sha)
        suggested_test = generate_test(change_to_process, commit_sha)
        
        update_payload = {
            "status": "Completed",
            "ai_summary": summary,
            "ai_suggested_test": suggested_test
        }
        doc_ref.update(update_payload)

        print(f"Successfully augmented analysis for {commit_sha}.")
        return "Augmentation complete.", 200

    except Exception as e:
        print(f"An unexpected error occurred during augmentation: {e}")
        DB.collection("analysis_results").document(commit_sha).update({"status": "Augmentation_Failed", "error": str(e)})
        raise e

def get_class_summary(full_code):
    """Makes a call to Gemini to summarize the purpose of a Java class."""
    if not full_code:
        return "No source code provided to summarize."
    
    print("Generating a summary of the class purpose...")
    
    prompt = f"""
    Analyze the following Java source code and describe its primary business purpose in a single sentence.
    For example, "This class manages pet owner records, allowing for creation, retrieval, and updates."

    Source Code:
    ```java
    {full_code}
    ```
    """
    try:
        # We add a short delay here as well to be respectful of the API quota
        time.sleep(1) 
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Could not generate class summary. Error: {e}")
        return "Could not be determined."

def generate_summary(change, analysis_data, commit_sha):
    """
    Builds the most context-rich prompt by first generating a summary of the
    class itself, then using that to inform the final business impact summary.
    """
    print("Generating summary...")
    change_type = change['type']
    class_name = change.get('class', 'N/A')
    method_name = change.get('method', 'N/A')
    impacted_count = len(analysis_data.get("impacted_components", {}).get("direct", []))
    impacted_list = ", ".join(analysis_data.get("impacted_components", {}).get("direct", []))

    # --- NEW: Get a summary of what the class does ---
    source_code_to_summarize = ""
    try:
        # For deletions, we need to get the code from the PARENT commit to know what it *used* to do
        if change['type'] == 'DC':
            commit_details_res = requests.get(f"{GITHUB_API_URL}/commits/{commit_sha}", headers=HEADERS)
            commit_details_res.raise_for_status()
            parent_sha = commit_details_res.json()["parents"][0]["sha"]
            content_url = f"{GITHUB_API_URL}/contents/{change['file']}?ref={parent_sha}"
        else: # For additions or modifications, use the current commit
            content_url = f"{GITHUB_API_URL}/contents/{change['file']}?ref={commit_sha}"

        res = requests.get(content_url, headers=HEADERS)
        if res.status_code == 200:
            source_code_to_summarize = base64.b64decode(res.json()["content"]).decode('utf-8')
    except Exception as e:
        print(f"Could not fetch source code for summary. Error: {e}")
    
    class_purpose_summary = get_class_summary(source_code_to_summarize)
    # --- END NEW SECTION ---


    api_context = "" # (This logic remains the same)
    # ... (The rest of the API and UI context logic is unchanged)

    change_desc = "unknown"
    if change_type == "CM":
        change_desc = f"the logic inside the method '{method_name}' was modified"
    elif change_type == "AM":
        change_desc = f"a new method '{method_name}' was added"
    elif change_type == "DC":
        change_desc = f"this class was deleted"

    prompt = f"""
    You are a senior software architect reviewing a pull request for a legacy Java application.
    Analyze the following code change and its impact, then provide a concise, business-focused summary for the pull request description.
    Focus on the highest-level impact (UI and APIs).

    Context:
    - Class Purpose: {class_purpose_summary}
    - Change Description: In this class, {change_desc}.
    - Downstream Code Impact: This change directly impacts {impacted_count} other backend components.{api_context} 

    Task:
    Based on all of this context, write a 2-3 sentence summary for a project manager.
    Prioritize mentioning the business purpose of the change and any risks to APIs or UI components.
    """
    return model.generate_content(prompt).text

def get_test_style_examples(source_file_path, commit_sha):
    """
    Finds the corresponding test file for a given source file and fetches its content
    to be used as a style example for the AI.
    """
    print(f"Searching for test style examples for: {source_file_path}")
    # A common Java convention: src/main/java -> src/test/java and Class.java -> ClassTests.java
    test_path_guess1 = source_file_path.replace("src/main/java", "src/test/java").replace(".java", "Tests.java")
    test_path_guess2 = source_file_path.replace("src/main/java", "src/test/java").replace(".java", "Test.java")

    test_file_path = None
    try:
        # Check if either of the guessed test files exist in the graph for this commit
        graph_ref = DB.collection("graph_snapshots").document(commit_sha).collection("graph")
        doc1 = graph_ref.where("file_path", "==", test_path_guess1).limit(1).get()
        if doc1:
            test_file_path = test_path_guess1
        else:
            doc2 = graph_ref.where("file_path", "==", test_path_guess2).limit(1).get()
            if doc2:
                test_file_path = test_path_guess2
        
        if test_file_path:
            print(f"Found corresponding test file: {test_file_path}")
            content_url = f"{GITHUB_API_URL}/contents/{test_file_path}?ref={commit_sha}"
            res = requests.get(content_url, headers=HEADERS)
            if res.status_code == 200:
                test_file_content = base64.b64decode(res.json()["content"]).decode('utf-8')
                # Return the content formatted for the prompt
                return f"""
                For context, here is the full content of an existing test file from this project. Please match its style (e.g., imports, mocking, assertion style).

                Example Test File (`{test_file_path}`):
                ```java
                {test_file_content}
                ```
                """
        return "" # Return empty string if no test file is found
    except Exception as e:
        print(f"Could not retrieve test style examples. Error: {e}")
        return "" # Return empty string on error

def generate_test(change, commit_sha):
    """
    Fetches full class content and existing test examples to generate
    a targeted, style-consistent unit test.
    """
    print("Generating test...")
    if change['type'] == 'DC':
        return "No test suggestion for deleted classes."

    file_path = change['file']
    try:
        content_url = f"{GITHUB_API_URL}/contents/{file_path}?ref={commit_sha}"
        res = requests.get(content_url, headers=HEADERS)
        res.raise_for_status()
        full_code = base64.b64decode(res.json()["content"]).decode('utf-8')
    except Exception as e:
        print(f"Could not fetch file content for {file_path}. Error: {e}")
        return "Could not fetch source code to generate a test."

    # --- NEW: Get style examples from existing tests ---
    test_style_context = get_test_style_examples(file_path, commit_sha)

    method_name = change.get('method', 'N/A')

    prompt = f"""
    You are a senior QA engineer specializing in JUnit 5.
    You are writing a new unit test for a change made to a legacy Java class.

    Full Class Code to be Tested:
    ```java
    {full_code}
    ```
    {test_style_context}
    Task:
    Write a single, focused JUnit 5 test method that specifically validates the functionality of the '{method_name}' method.
    The test should be clear, concise, and follow best practices.
    Only output the raw Java code for the test method, do not include the class definition or any explanations.
    """
    return model.generate_content(prompt).text
    
    # --- THIS LINE IS NOW CORRECT ---
    method_name = change.get('method', 'N/A')

    prompt = f"""
    You are a senior QA engineer specializing in JUnit 5.
    You are writing a new unit test for a change made to a legacy Java class.

    Full Class Code:
    ```java
    {full_code}
    ```

    Task:
    Write a single, focused JUnit 5 test method that specifically validates the functionality of the '{method_name}' method.
    The test should be clear, concise, and follow best practices for mocking if necessary (you can assume Mockito is available).
    Only output the raw Java code for the test method, do not include the class definition or any explanations.
    """
    return model.generate_content(prompt).text

