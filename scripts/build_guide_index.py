#!/usr/bin/env python3
"""
Script to build Guide_Documents_Metadata_Index.json from processed guide files
"""

import os
import json
import re
import shutil
from datetime import datetime
from collections import defaultdict

# Paths
INPUT_DIR = "VECTOR_GUIDES_JSON"
OUTPUT_FILE = "Guide_Documents_Metadata_Index.json"
EXISTING_INDEX_FILE = "Guide_Documents_Metadata_Index.json"

# Common question patterns by guide type
QUESTION_TEMPLATES = {
    # How-to guides
    "How to": [
        "How do I {topic}?",
        "What are the steps to {topic}?",
        "Can you show me how to {topic}?"
    ],
    # Work instructions
    "WI": [
        "What is the procedure for {topic}?",
        "What are the steps in the work instruction for {topic}?",
        "How should I complete {topic}?"
    ],
    # User guides
    "User Guide": [
        "How do I use {topic}?",
        "What features does {topic} have?",
        "How can I get started with {topic}?"
    ],
    # Default for all other guide types
    "default": [
        "How do I {topic}?",
        "What is the process for {topic}?",
        "Can you guide me through {topic}?"
    ]
}

def extract_guide_topic(title):
    """Extract the main topic from the guide title"""
    # Remove common prefixes like "How to", "Guide for", etc.
    title = re.sub(r'^(?:How to|Guide for|Guide to|WI)\s+', '', title, flags=re.IGNORECASE)
    
    # Remove common words
    common_words = ["and", "for", "the", "of", "in", "on", "to", "a", "an"]
    words = title.lower().split()
    key_words = [word for word in words if word not in common_words]
    
    # Join the remaining words to form a topic
    if key_words:
        return " ".join(key_words)
    return title  # Fallback to the original title

def determine_guide_type(title):
    """Determine the type of guide based on its title"""
    if title.lower().startswith("how to"):
        return "How to"
    elif "user guide" in title.lower():
        return "User Guide"
    elif title.startswith("WI "):
        return "WI"
    else:
        return "default"

def generate_questions(guide_number, title):
    """Generate relevant questions based on the guide type and title"""
    # Determine guide type
    guide_type = determine_guide_type(title)
    
    # Get question templates for this guide type
    templates = QUESTION_TEMPLATES.get(guide_type, QUESTION_TEMPLATES["default"])
    
    # Extract main topic
    topic = extract_guide_topic(title)
    
    # Generate questions using templates
    questions = [template.format(topic=topic) for template in templates]
    return questions

def generate_description(guide_json):
    """Generate a description based on the guide content"""
    description = ""
    
    # Try to use the overview section if available
    if guide_json.get("sections", {}).get("overview"):
        description = guide_json["sections"]["overview"]
        # Truncate if too long
        if len(description) > 200:
            description = description[:197] + "..."
    
    # Fallback to steps if overview not available
    elif guide_json.get("sections", {}).get("steps"):
        description = "Steps to " + guide_json.get("title", "complete this task") + "."
    
    # Last resort: use the first 200 characters of full text
    elif guide_json.get("full_text"):
        description = guide_json["full_text"][:197] + "..."
    
    if not description:
        description = f"Guide for {guide_json.get('title', 'completing this task')}."
    
    return description

def backup_existing_index():
    """Create a backup of the existing index file if it exists"""
    if os.path.exists(EXISTING_INDEX_FILE):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{os.path.splitext(EXISTING_INDEX_FILE)[0]}_{timestamp}.json"
        
        try:
            shutil.copy2(EXISTING_INDEX_FILE, backup_filename)
            print(f"Created backup of existing index at: {backup_filename}")
            return True
        except Exception as e:
            print(f"Warning: Could not create backup: {e}")
            return False
    
    return False

def load_existing_index():
    """Load the existing guide index if available"""
    existing_data = {"Guide Documents": []}
    if os.path.exists(EXISTING_INDEX_FILE):
        try:
            with open(EXISTING_INDEX_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load existing index: {e}")
    
    # Create a lookup by filename for easy reference
    existing_lookup = {}
    for item in existing_data.get("Guide Documents", []):
        if "File" in item:
            filename = item["File"]
            existing_lookup[filename] = item
    
    return existing_data, existing_lookup

def main():
    print(f"Building guide index from JSON files in {INPUT_DIR}...")
    
    # Backup existing index before proceeding
    backup_existing_index()
    
    # Load existing index if available
    existing_data, existing_lookup = load_existing_index()
    
    # Initialize new index
    guide_documents = []
    
    # Process each JSON file
    json_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.json')]
    print(f"Found {len(json_files)} JSON files to process.")
    
    for json_file in json_files:
        file_path = os.path.join(INPUT_DIR, json_file)
        
        try:
            # Load JSON data
            with open(file_path, 'r', encoding='utf-8') as f:
                guide_json = json.load(f)
            
            # Extract basic info
            guide_number = guide_json.get("guide_number", "unknown")
            title = guide_json.get("title", "")
            
            # Use JSON filename as reference
            txt_filename = json_file
            
            # Check if this guide already exists in the index
            if txt_filename in existing_lookup:
                # Use existing entry but ensure it has all required fields
                entry = existing_lookup[txt_filename]
                if "Document" not in entry:
                    entry["Document"] = title
                if "Description" not in entry:
                    entry["Description"] = generate_description(guide_json)
                if "Questions Answered" not in entry:
                    entry["Questions Answered"] = generate_questions(guide_number, title)
            else:
                # Create new entry
                entry = {
                    "Document": title,
                    "File": txt_filename,
                    "Description": generate_description(guide_json),
                    "Questions Answered": generate_questions(guide_number, title)
                }
            
            guide_documents.append(entry)
            print(f"Processed: {json_file}")
            
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
    
    # Create final output
    output_data = {
        "Guide Documents": guide_documents
    }
    
    # Write to file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
    
    print(f"\nIndex build complete. Created {OUTPUT_FILE} with {len(guide_documents)} guide entries.")

if __name__ == "__main__":
    main() 