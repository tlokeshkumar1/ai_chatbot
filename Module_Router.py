import os
import re
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

# Complete list of valid modules in AMS
MODULES = [
    "RPA",
    "SAP-FICO",
    "SAP-SD",
    "SAP ABAP",
    "SAP-BASIS",
    "SAP-PM",
    "SAP-MM",
    "SAP-PP",
    "SAP-DBM",
    "SAP-SF",
    "SAP-PS",
    "SAP-CPI",
    "SAP-PMO",
    "AWS",
    "SAP-Analytics",
    "SAP-BW",
    "SAP-Delivery",
    "SAP-HCM",
    "SAP-QM",
    "SAP-PI",
    "Dot Net Technologies",
    "SAP",
    "Infra Cloud",
    "Freelancer",
    "SAP-EWM",
    "SAP EHS",
    "SAP-SOLUTION MANAGER",
    "SAP-DMS",
    "SAP-PPQM",
    "Support",
    "SAP-VIM",
    "Siemens",
    "SAP-VSS",
    "Linux Admin",
    "SAP SAC",
    "SAP ARIBA",
    "Mendix",
    "HRBP",
    "Inside Sales",
    "SAP-AI",
    "SAP-BTP",
    "Data Analytics & AI",
    "SAP PPVC",
    "SAP SDM",
    "UI / UX"
]

# Rule-based fallback domain keywords
MODULE_KEYWORDS = {
    "SAP-FICO": [r"\bfico\b", r"\bfinance\b", r"\bg/l\b", r"\bgl\b", r"\balert\b", r"\binvoice\b", r"\bpayment\b", r"\bledger\b", r"\basset accounting\b", r"\baccounts payable\b", r"\baccounts receivable\b", r"\btax\b"],
    "SAP-SD": [r"\bsd\b", r"\bsales\b", r"\bdistribution\b", r"\bbilling\b", r"\bshipping\b", r"\bdelivery\b", r"\bpricing\b", r"\bsales order\b"],
    "SAP ABAP": [r"\babap\b", r"\bdump\b", r"\bsyntax error\b", r"\bbapi\b", r"\bbadi\b", r"\bsmartform\b", r"\bsapscript\b", r"\bzprogram\b", r"\benhancement\b", r"\bse38\b", r"\bse80\b"],
    "SAP-BASIS": [r"\bbasis\b", r"\bauthorization\b", r"\btransport\b", r"\bst03\b", r"\bsm50\b", r"\bkernel\b", r"\buser lock\b", r"\brole\b", r"\btcode access\b", r"\bsystem lock\b", r"\blogin\b", r"\bauthenticat\w*\b"],
    "SAP-MM": [r"\bmm\b", r"\bmaterial\b", r"\bpurchase\b", r"\bvendor\b", r"\binventory\b", r"\bgrn\b", r"\bpo\b", r"\brequisition\b", r"\bstock\b"],
    "SAP-PP": [r"\bpp\b", r"\bproduction\b", r"\bmrp\b", r"\bbom\b", r"\bwork center\b", r"\brouting\b"],
    "SAP-PM": [r"\bpm\b", r"\bplant maintenance\b", r"\bequipment\b", r"\bwork order\b", r"\bnotification\b"],
    "SAP-QM": [r"\bqm\b", r"\bquality\b", r"\binspection\b", r"\bbatch\b", r"\bcertificate\b"],
    "SAP-HCM": [r"\bhcm\b", r"\bpayroll\b", r"\bemployee\b", r"\bleave\b", r"\battendance\b", r"\bhuman capital\b"],
    "HRBP": [r"\bhrbp\b", r"\bhr partner\b", r"\bhuman resource\b"],
    "SAP-BW": [r"\bbw\b", r"\bbusiness warehouse\b", r"\bcube\b", r"\bdso\b"],
    "SAP SAC": [r"\bsac\b", r"\banalytics cloud\b"],
    "SAP-Analytics": [r"\banalytics\b", r"\bbi\b", r"\bdashboard\b", r"\breporting\b"],
    "SAP-CPI": [r"\bcpi\b", r"\bcloud platform integration\b", r"\biflow\b"],
    "SAP-PI": [r"\bpi\b", r"\bprocess integration\b", r"\bxi\b"],
    "SAP-VIM": [r"\bvim\b", r"\bopentext\b", r"\bvendor invoice management\b"],
    "SAP ARIBA": [r"\bariba\b", r"\bsourcing\b", r"\bprocurement\b"],
    "SAP-SF": [r"\bsf\b", r"\bsuccessfactors\b"],
    "AWS": [r"\baws\b", r"\bec2\b", r"\bs3\b", r"\bamazon\b", r"\bcloud\b", r"\biam\b", r"\bvpc\b"],
    "Infra Cloud": [r"\binfra\b", r"\binfrastructure\b", r"\bazure\b", r"\bgcp\b", r"\bcloud infra\b"],
    "Linux Admin": [r"\blinux\b", r"\bubuntu\b", r"\bredhat\b", r"\bcentos\b", r"\bbash\b", r"\bssh\b", r"\broot\b", r"\bserver reboot\b"],
    "Dot Net Technologies": [r"\b\.net\b", r"\bdotnet\b", r"\bc#\b", r"\basp\.net\b", r"\bvisual studio\b"],
    "RPA": [r"\brpa\b", r"\bbot\b", r"\buipath\b", r"\bautomation anywhere\b", r"\bblue prism\b"],
    "UI / UX": [r"\bui\b", r"\bux\b", r"\bfrontend\b", r"\bcss\b", r"\bhtml\b", r"\blayout\b", r"\buser interface\b"],
    "Mendix": [r"\bmendix\b", r"\blow code\b"],
    "SAP-AI": [r"\bsap ai\b", r"\bai core\b", r"\bJoule\b", r"\sGenAI\b", r"\bagents\b", r"\bagentic ai\b", r"\bgenerative ai\b"],
    "Data Analytics & AI": [r"\bdata analytics\b", r"\bmachine learning\b", r"\bml\b", r"\bai\b", r"\bllm\b"],
    "Support": [r"\bsupport\b", r"\bhelpdesk\b", r"\bgeneral\b"]
}


def _classify_with_agent(description: str, api_key: str) -> str:
    """Call Google Gemini API as an AI Agent to classify the ticket description into a valid AMS module."""
    models = ["gemini-2.5-flash", "gemini-1.5-flash"]
    modules_str = ", ".join(MODULES)
    
    prompt = (
        f"You are an expert IT Ticket Routing Agent.\n"
        f"Analyze the following ticket description and assign it to the MOST appropriate module from this list:\n"
        f"[{modules_str}]\n\n"
        f"Ticket Description: \"{description}\"\n\n"
        f"Instructions:\n"
        f"1. Respond ONLY with the exact module name from the list provided above.\n"
        f"2. Do not include any extra punctuation, explanations, or quotes."
    )
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 30
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            if res.ok:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                text_clean = re.sub(r'[^A-Za-z0-9\s/&\.-]', '', text).strip()
                
                # Verify exact or case-insensitive match against valid MODULES
                for mod in MODULES:
                    if mod.lower() == text_clean.lower():
                        return mod
                # Partial match
                for mod in MODULES:
                    if mod.lower() in text_clean.lower() or text_clean.lower() in mod.lower():
                        return mod
        except Exception as e:
            print(f"Gemini API routing failed with model {model}: {e}")
            continue
            
    return None


def _classify_with_rules(description: str) -> str:
    """Fallback rule-based keyword matching for ticket description."""
    desc_lower = description.lower()
    
    # Priority match for specific module keywords
    for mod, patterns in MODULE_KEYWORDS.items():
        for pat in patterns:
            if re.search(pat, desc_lower):
                return mod

    # Generic SAP check
    if "sap" in desc_lower:
        return "SAP"
        
    return "Support"


def assign_module(description: str) -> str:
    """
    Main entry point for AI Agent module assignment based on ticket description.
    Uses Gemini API AI Agent if key is available, falling back to rule-based classification.
    """
    if not description or not str(description).strip():
        return "Support"

    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key and api_key != "your_gemini_api_key":
        agent_res = _classify_with_agent(description.strip(), api_key)
        if agent_res:
            return agent_res

    return _classify_with_rules(description.strip())