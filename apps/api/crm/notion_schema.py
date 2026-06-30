import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.logging import log_stage

_schema: Dict[str, Any] = {}

def get_mapping() -> Dict[str, str]:
    mapping_file = Path(__file__).parent / "notion_mapping.json"
    if mapping_file.exists():
        with open(mapping_file, "r") as f:
            return json.load(f)
    return {}

def load_schema(ds_properties: Dict[str, Any]) -> None:
    global _schema
    _schema = ds_properties

def get_schema() -> Dict[str, Any]:
    return _schema

def get_property_info(notion_prop_name: str) -> Optional[Dict[str, Any]]:
    return _schema.get(notion_prop_name)

def resolve_notion_status(notion_prop_name: str, backend_status: str) -> Optional[str]:
    prop_info = get_property_info(notion_prop_name)
    if not prop_info or prop_info.get("type") not in ("status", "select"):
        return backend_status[:100] if backend_status else None
        
    options = []
    if prop_info["type"] == "status":
        options = prop_info.get("status", {}).get("options", [])
    elif prop_info["type"] == "select":
        options = prop_info.get("select", {}).get("options", [])

    if not options:
        return backend_status[:100]

    valid_names = [opt["name"] for opt in options]
    
    # Exact match first
    for name in valid_names:
        if name.lower() == backend_status.lower():
            return name
            
    # Substring fuzzy match
    b_lower = backend_status.lower()
    for name in valid_names:
        n_lower = name.lower()
        if n_lower in b_lower or b_lower in n_lower:
            return name
            
    # Common mappings fallback
    common_map = {
        "queued": ["pending", "to-do", "to do", "queued"],
        "syncing_crm": ["syncing", "in progress", "progress"],
        "syncing": ["syncing", "in progress", "progress"],
        "completed": ["synced", "done", "complete", "completed"],
        "synced": ["synced", "done", "complete", "completed"],
        "failed": ["failed", "error"],
        "duplicate": ["duplicate", "skipped"],
        "pending": ["queued", "to-do", "to do", "pending"]
    }
    
    fallbacks = common_map.get(b_lower, [])
    for fallback in fallbacks:
        for name in valid_names:
            if fallback in name.lower() or name.lower() in fallback:
                return name
                
    # If no match found, fallback to the first 'To-do' group option if status, else just first option
    log_stage("notion_schema", f"Could not map status '{backend_status}' for {notion_prop_name}. Falling back to default.")
    
    if prop_info["type"] == "status" and "groups" in prop_info["status"]:
        for group in prop_info["status"]["groups"]:
            if group["name"] == "To-do" and group.get("option_ids"):
                opt_id = group["option_ids"][0]
                for opt in options:
                    if opt["id"] == opt_id:
                        return opt["name"]
                        
    return valid_names[0] if valid_names else backend_status[:100]
