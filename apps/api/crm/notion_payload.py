from typing import Any, Dict
from core.logging import log_stage
from crm.notion_schema import get_mapping, get_property_info, resolve_notion_status

def _format_value(prop_type: str, value: Any, notion_prop_name: str) -> Any:
    if value is None:
        return None
        
    if prop_type == "title":
        return {"title": [{"text": {"content": str(value)[:2000]}}]}
    elif prop_type == "rich_text":
        return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
    elif prop_type == "number":
        try:
            return {"number": float(value)}
        except (ValueError, TypeError):
            log_stage("notion_payload", f"Skipped invalid number for {notion_prop_name}", value=value)
            return None
    elif prop_type == "url":
        sval = str(value)
        return {"url": sval[:2000] if sval.startswith("http") else None}
    elif prop_type == "email":
        sval = str(value)
        return {"email": sval if "@" in sval else None}
    elif prop_type == "status":
        valid_status = resolve_notion_status(notion_prop_name, str(value))
        return {"status": {"name": valid_status}}
    elif prop_type == "select":
        valid_status = resolve_notion_status(notion_prop_name, str(value))
        return {"select": {"name": valid_status}}
    elif prop_type == "checkbox":
        return {"checkbox": bool(value)}
    
    # Unhandled types (like relation, multi-select, date) can be safely skipped for now
    log_stage("notion_payload", f"Unsupported property type {prop_type} for {notion_prop_name}")
    return None

def build_notion_payload(ctx: dict) -> Dict[str, Any]:
    mapping = get_mapping()
    payload = {}
    
    # Base Lead fields
    lead = ctx["lead"]
    internal_data = {
        "name": lead.name,
        "company": lead.company,
        "email": lead.email,
        "location": lead.location if hasattr(lead, "location") else None,
        "status": lead.status,
        "crm_status": ctx.get("crm_status_value", "Pending"),
        "errors": lead.error_message,
        
        "icp_score": ctx.get("score"),
        "combined_score": ctx.get("score"), # Fallback if they use combined score
        
        "linkedin": ctx.get("linkedin"),
        "linkedin_person": ctx.get("linkedin"),
        
        "signals": ctx.get("signals"),
        "top_signal": ctx.get("top_signal"),
        "summary": ctx.get("summary"),
    }
    
    drafts = ctx.get("drafts", [])
    if len(drafts) > 0:
        internal_data["outreach_subject_v1"] = drafts[0].subject
        internal_data["outreach_email_v1"] = drafts[0].body
    if len(drafts) > 1:
        internal_data["outreach_subject_v2"] = drafts[1].subject
        internal_data["outreach_email_v2"] = drafts[1].body
    
    # Merge context dynamically mapped fields (from enrichment profile)
    profile = ctx.get("profile_dict", {})
    for k, v in profile.items():
        if k not in internal_data:
            internal_data[k] = v
            
    # Parse company size min/max if present
    c_size = internal_data.get("company_size")
    if c_size and c_size != "Data not found":
        import re
        nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", c_size)]
        if len(nums) == 1:
            internal_data["company_size_min"] = str(nums[0])
            internal_data["company_size_max"] = str(nums[0])
        elif len(nums) >= 2:
            internal_data["company_size_min"] = str(nums[0])
            internal_data["company_size_max"] = str(nums[1])
            
    # Now build the payload based on the mapping file
    for internal_key, notion_prop_name in mapping.items():
        if internal_key not in internal_data:
            continue
            
        raw_val = internal_data[internal_key]
        if raw_val is None or raw_val == "":
            continue
            
        prop_info = get_property_info(notion_prop_name)
        if not prop_info:
            log_stage("notion_payload", f"Missing Notion property '{notion_prop_name}' mapped from '{internal_key}'")
            continue
            
        prop_type = prop_info.get("type")
        formatted = _format_value(prop_type, raw_val, notion_prop_name)
        
        if formatted is not None:
            # Prevent sending None inside url or email if parsing failed
            if prop_type in ("url", "email") and not list(formatted.values())[0]:
                continue
            payload[notion_prop_name] = formatted

    return payload
