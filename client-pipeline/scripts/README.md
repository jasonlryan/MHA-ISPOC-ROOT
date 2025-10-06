# DOCX to JSON Converter

This script converts DOCX policy documents to structured JSON format for use in vector stores and retrieval systems.

## Features

- Extracts policy ID and title from filenames
- Identifies sections within documents (summary, purpose, scope, etc.)
- Preserves document metadata
- Creates structured JSON files ready for vector embedding

## Requirements

- Python 3.6+
- python-docx library

## Installation

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

1. Ensure your DOCX files are in the "raw policies" folder
2. Run the script:

```bash
python convert_to_json.py
```

3. The processed JSON files will be created in the "VECTOR_JSON" folder

## Output Format

Each JSON file contains:

- **id**: Policy ID extracted from filename
- **title**: Policy title extracted from filename
- **filename**: Original filename
- **extracted_date**: Date of processing
- **metadata**: Document properties from the DOCX file
- **full_text**: Complete document text
- **sections**: Structured sections like purpose, scope, procedure, etc.

## Example Output

```json
{
  "id": "HR4.13",
  "title": "DBS Policy and Procedure",
  "filename": "HR4.13 DBS Policy and Procedure.docx",
  "extracted_date": "2023-11-30",
  "metadata": {
    "author": "MHA",
    "created": "2023-04-15"
  },
  "full_text": "The full text of the document...",
  "sections": {
    "purpose": "This policy outlines...",
    "scope": "This policy applies to...",
    "procedure": "The following procedures must be followed..."
  }
}
```
