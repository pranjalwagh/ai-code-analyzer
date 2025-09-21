Change-Guard: AI-Powered Change Impact Analysis
An automated engine for validating changes on legacy codebases. Change-Guard analyzes the ripple effects of code commits across UI, APIs, and data models to reduce risk and accelerate release cycles.

🚩 The Problem
When working with large, legacy codebases, a seemingly small change can have unforeseen consequences, leading to:

Slow Release Cycles: Manual impact analysis and broad, expensive regression testing create significant delays.

High Defect Rates: Unseen ripple effects across different layers of the application lead to post-release bugs.

Developer Hesitation: Teams become reluctant to refactor or modernize legacy code due to the fear of triggering regressions.

This project aims to solve these issues by providing an automated, intelligent, and insightful analysis of every pull request.

✨ The Solution
Change-Guard is a CI/CD-integrated tool that provides a multi-layered analysis of code changes. When a developer opens a pull request, it automatically:

Performs a Semantic Diff: Understands the code changes beyond a simple text comparison, identifying added, deleted, and modified methods and classes.

Builds a Point-in-Time, Full-Stack Dependency Graph: For each commit, it constructs a fresh, perfectly accurate map of the entire application, including backend class dependencies, API endpoints, and which UI components call those APIs.

Maps the Impact Radius: Traverses this commit-specific graph to identify all potentially affected components across the full stack.

Generates Deeply Contextual AI Insights: Uses a multi-step process with the Gemini API to provide intelligent summaries and tests. It first summarizes the purpose of the changed code, then uses that context—along with the full impact analysis—to generate a business-focused summary and a style-consistent unit test.

Delivers a Governance Dashboard: Presents the analysis in an interactive dashboard, providing a clear visual heatmap of the risk associated with the change.

🛠️ Technology Stack
This project leverages a modern, serverless-first architecture on Google Cloud.

Category

Technology

Frontend



Backend

(via Functions Framework)

Cloud & DevOps



Generative AI

(Gemini 1.5 Flash)

Database

(For storing analysis results & dependency graphs)

🏗️ Architecture
The application follows a microservices-based approach using Google Cloud Functions, orchestrated by a Cloud Build CI/CD pipeline.

Dynamic Analysis Workflow
The analysis is performed on a per-commit basis to ensure maximum accuracy:

A commit triggers a Cloud Build pipeline.

Cloud Build invokes the Orchestrator Cloud Function.

The Orchestrator downloads a snapshot of the repository, parses every file (Java & Frontend), and builds a commit-specific, full-stack dependency graph in Firestore.

The Orchestrator calls the Parser function to get a list of atomic code changes.

It calculates the impact radius by querying the new graph and saves the initial analysis to the analysis_results collection.

The Orchestrator then triggers the Gemini Augmenter function.

The Gemini Augmenter reads the analysis, gathers deep context (class summaries, API info, UI impact, test styles), performs its AI generation, and updates the final result in Firestore.

The Frontend (React app) listens to this collection to display the final, AI-enriched results.

✅ Current Status (As of 2025-09-18)
The entire backend, including the Core Analysis Engine and the Generative AI Layer, is complete and functional.

[x] Core Engine: Can build a point-in-time, full-stack dependency graph for any commit.

[x] Core Engine: Performs semantic diffing to detect AM, CM, DM, and DC changes.

[x] Core Engine: Calculates the direct impact ("blast radius") of a code change.

[x] AI Layer: Generates context-rich business impact summaries, including API and UI risks.

[x] AI Layer: Generates style-consistent, targeted unit tests.

[ ] Next Step: Implement the final piece: the Frontend Visualization Dashboard.

🚀 Getting Started: Local Development (Windows)
A PowerShell script (run-windows.ps1) automates the entire local setup process.

Prerequisites
Python (3.9+)

Node.js (16+)

Google Cloud SDK (gcloud CLI): Authenticate by running gcloud auth login and gcloud auth application-default login.

GitHub Personal Access Token (PAT): Generate a token with public_repo scope.

Running the Application
Configure the Script:

Open the run-windows.ps1 file at the root of the project.

Fill in your $GCP_PROJECT_ID and $GCP_REGION.

Fill in your $GITHUB_TOKEN by pasting your Personal Access Token.

Fill in your $FirebaseConfig object by copying it from your Firebase project settings.

Launch the Environment:

Open a standard PowerShell terminal (the one in VS Code is perfect).

Navigate to the project's root directory: cd path\to\change-guard

Set the execution policy for the current session (only needed once): Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process

Execute the script: .\run-windows.ps1

What to Expect
The script will install all dependencies and open four new terminal windows: one for the React frontend and one for each of the three backend microservices. Your browser will also open to http://localhost:3000.

To stop the environment, simply close the four new terminal windows.

📁 Project Structure

change-guard/
├── run-windows.ps1         # Master script for local development (contains GITHUB_TOKEN config)
├── cloudbuild.yaml         # CI/CD pipeline definition
├── functions/              # Backend Cloud Function services
│   ├── orchestrator/       # Coordinates the analysis workflow and builds the graph
│   ├── java_parser/        # Handles semantic diffing of Java code
│   └── gemini_augmenter/   # Integrates with the Gemini API
├── frontend/               # React dashboard application
│   └── src/
│       ├── App.js
│       └── firebase.js
└── scripts/
    └── post_github_comment.sh # Script for CI/CD to report results