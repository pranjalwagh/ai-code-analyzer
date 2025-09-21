#!/bin/bash

# This script is executed by Cloud Build. It fetches the analysis result
# from Firestore and posts it as a comment on the GitHub PR.

set -e # Exit immediately if a command exits with a non-zero status.

PROJECT_ID=$1
COMMIT_SHA=$2
PR_NUMBER=$3
REPO_FULL_NAME=$4 # e.g., "my-org/my-repo"

echo "Fetching analysis result for commit: $COMMIT_SHA"

# Use the gcloud CLI to fetch the document from Firestore and install jq
gcloud components install -q jq

ANALYSIS_JSON=$(gcloud firestore documents get "analysis_results/${COMMIT_SHA}" --project "${PROJECT_ID}" --format="json")

if [[ -z "$ANALYSIS_JSON" ]]; then
  echo "Error: Could not retrieve analysis result from Firestore."
  exit 1
fi

# --- FIX: Use the correct field name 'ai_summary' ---
SUMMARY=$(echo $ANALYSIS_JSON | jq -r '.fields.ai_summary.stringValue // "AI summary is being generated..."')
STATUS=$(echo $ANALYSIS_JSON | jq -r '.fields.status.stringValue // "Unknown"')

# Since risk_score isn't implemented, we'll use a placeholder for the MVP
RISK_TEXT="Not Calculated" 

DASHBOARD_URL="https://${PROJECT_ID}.web.app"

# --- FIX: Construct the comment body more safely ---
COMMENT_BODY="### :robot: ChangeGuard Analysis Complete\n\n"
COMMENT_BODY+="**Commit:** \`${COMMIT_SHA}\`\n"
COMMENT_BODY+="**Status:** ${STATUS}\n"
COMMENT_BODY+="**Overall Risk:** **${RISK_TEXT}**\n\n"
COMMENT_BODY+="---\n\n"
COMMENT_BODY+="#### AI-Generated Summary:\n${SUMMARY}\n\n"
COMMENT_BODY+="---\n\n"
COMMENT_BODY+="[**View Full Interactive Report &rarr;**](${DASHBOARD_URL}?commit=${COMMIT_SHA})"

# Use jq to create a valid JSON payload, which is much safer
JSON_PAYLOAD=$(jq -n --arg body "$COMMENT_BODY" '{"body": $body}')

echo "Posting comment to PR #${PR_NUMBER} in repo ${REPO_FULL_NAME}"

# The GITHUB_TOKEN is injected as a secret environment variable in cloudbuild.yaml
curl -s -X POST \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO_FULL_NAME}/issues/${PR_NUMBER}/comments" \
  -d "$JSON_PAYLOAD"

echo "Comment posted successfully."