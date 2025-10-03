# streamlit_agent_freefire.py
# Streamlit UI wrapper around your original agent_freefire.py code.
# Saves: streamlit_agent_freefire.py

import os
import asyncio
import json
import requests
from urllib.parse import urlparse, parse_qs

import streamlit as st

# ----------------------------
# Import your agent framework
# ----------------------------
from agents import Agent, Runner, function_tool, ModelSettings
from connecton import config

# ----------------------------
# 1) Credentials extraction
# ----------------------------
CREDENTIALS_URL = (
    "https://proapis.hlgamingofficial.com/main/games/freefire/account/api"
    "?sectionName=AllData&PlayerUid=2119242559&region=pk"
    "&useruid=9z4Dnjvu6oVKHWugsOs68ITa7C33"
    "&api=ueinnPfToKK2cVn8yIwpizTo80Gsau"
)

def extract_credentials_from_url(url: str):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return qs.get("useruid", [None])[0], qs.get("api", [None])[0]

_default_useruid, _default_api = extract_credentials_from_url(CREDENTIALS_URL)
FIXED_USERUID = os.getenv("FREEFIRE_USERUID", _default_useruid)
FIXED_API = os.getenv("FREEFIRE_API", _default_api)

def _mask(s: str) -> str:
    if not s:
        return ""
    if len(s) <= 8:
        return s[0] + "..." + s[-1]
    return s[:4] + "..." + s[-4:]

# ----------------------------
# Streamlit session defaults
# ----------------------------
st.markdown("# Free Fire Account — Agent UI")
if "last_ff_api_response" not in st.session_state:
    st.session_state["last_ff_api_response"] = None
if "last_ff_status_code" not in st.session_state:
    st.session_state["last_ff_status_code"] = None
if "last_ff_request_payload" not in st.session_state:
    st.session_state["last_ff_request_payload"] = None
if "last_agent_result" not in st.session_state:
    st.session_state["last_agent_result"] = None

# ----------------------------
# Original get_ff_account tool (adapted exactly)
# ----------------------------
@function_tool(
    name_override="Get_FreeFire_Account",
    description_override="Fetch Free Fire account info by PlayerUid and region (only these two are changeable)."
)
def get_ff_account(PlayerUid: str, region: str = "pk") -> dict:
    """
    Calls:
      POST https://proapis.hlgamingofficial.com/main/games/freefire/account/api
    with JSON payload:
      {"sectionName":"AllData","PlayerUid": <PlayerUid>, "region": <region>,
       "useruid": FIXED_USERUID, "api": FIXED_API}
    Returns parsed JSON or structured error dict.
    """

    url = "https://proapis.hlgamingofficial.com/main/games/freefire/account/api"

    # Basic validation
    PlayerUid = str(PlayerUid).strip()
    if not PlayerUid:
        return {"error": "missing_PlayerUid", "details": "PlayerUid is required and cannot be empty."}

    region = (str(region).strip() or "pk")

    payload = {
        "sectionName": "AllData",
        "PlayerUid": PlayerUid,   # NOTE: case-sensitive key exactly as API expects
        "region": region,
        "useruid": FIXED_USERUID,
        "api": FIXED_API
    }

    # Save request payload into session_state if available
    try:
        st.session_state["last_ff_request_payload"] = {"PlayerUid": PlayerUid, "region": region}
    except Exception:
        # If called outside Streamlit context, ignore
        pass

    try:
        resp = requests.post(url, json=payload, timeout=15)
    except requests.exceptions.RequestException as e:
        err = {"error": "request_exception", "details": str(e)}
        try:
            st.session_state["last_ff_api_response"] = err
            st.session_state["last_ff_status_code"] = None
        except Exception:
            pass
        return err

    # Save raw response (JSON or text)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text

    try:
        st.session_state["last_ff_api_response"] = body
        st.session_state["last_ff_status_code"] = resp.status_code
    except Exception:
        pass

    # Non-2xx responses
    if not (200 <= resp.status_code < 300):
        return {
            "error": "http_error",
            "status_code": resp.status_code,
            "details": body,
            "request_payload": {"PlayerUid": PlayerUid, "region": region}
        }

    # 2xx: return parsed JSON or invalid_json error
    try:
        return resp.json()
    except ValueError:
        return {
            "error": "invalid_json",
            "details": resp.text[:2000],
            "request_payload": {"PlayerUid": PlayerUid, "region": region}
        }

# ----------------------------
# Agent (same as your original)
# ----------------------------
personal_agent = Agent(
    name="FreeFireAgent",
    instructions="""
You are an assistant specialized in Free Fire account lookups.
When the user asks for Free Fire account details, call the Get_FreeFire_Account tool with the player's PlayerUid and optionally a region (defaults to 'pk').
Do not invent data — only use the tool output to form conclusions. After calling the tool, summarize key fields and present any troubleshooting notes if the tool returns an error.
""",
    tools=[get_ff_account],
    model_settings=ModelSettings(temperature=0.0, tool_choice="required", max_tokens=500)
)

# ----------------------------
# Helper to run Runner.run synchronously
# ----------------------------
def run_runner_sync(prompt_text: str):
    """
    Runs Runner.run(personal_agent, prompt_text, run_config=config) synchronously.
    Returns the runner result or a dict with error.
    """
    try:
        result = asyncio.run(Runner.run(personal_agent, prompt_text, run_config=config))
        return result
    except Exception as e:
        return {"_runner_exception": str(e)}

# ----------------------------
# Streamlit UI
# ----------------------------


# Credentials area
if not FIXED_USERUID or not FIXED_API:
    st.warning("FREEFIRE_USERUID and FREEFIRE_API are not set as environment variables. You can enter them below (not recommended for production).")
    ui_useruid = st.text_input("Developer useruid (useruid)", value=_default_useruid or "")
    ui_api = st.text_input("API key (api)", value=_default_api or "", type="password")
    # If user provided values in UI, temporarily override globals for this run
   

col1, col2 = st.columns([2, 1])
with col1:
    player_uid = st.text_input("PlayerUid (required)", value="2119242559")
with col2:
    region = st.text_input("Region (default 'pk')", value="pk")

run_agent = st.button("Lookup (Agent)")
run_api_only = st.button("Call API only (no agent)")

summary_placeholder = st.empty()
raw_placeholder = st.empty()
download_placeholder = st.empty()

# Agent action
if run_agent:
    if not player_uid.strip():
        st.error("PlayerUid is required.")
    elif not FIXED_USERUID or not FIXED_API:
        st.error("Missing FREEFIRE_USERUID/FREEFIRE_API. Set env variables or enter them in the credential fields.")
    else:
        prompt = (
            f"Fetch Free Fire account info using the Get_FreeFire_Account tool for PlayerUid={player_uid} and region={region}. "
            "Then summarize the account with key fields (nickname, level, rank, likes,Guild Name) and at last write review about it ."
        )
        with st.spinner("Running agent (this may take a few seconds)..."):
            result = run_runner_sync(prompt)
            st.session_state["last_agent_result"] = result

        # show final_output if present
        final_output = None
        try:
            final_output = getattr(result, "final_output", None)
            if final_output is None:
                if isinstance(result, dict):
                    final_output = json.dumps(result, indent=2, ensure_ascii=False)
                else:
                    final_output = str(result)
        except Exception:
            final_output = str(result)

        summary_placeholder.subheader("Agent summary")
        summary_placeholder.code(final_output)

    
# API-only action
if run_api_only:
    if not player_uid.strip():
        st.error("PlayerUid is required.")
    elif not FIXED_USERUID or not FIXED_API:
        st.error("Missing FREEFIRE_USERUID/FREEFIRE_API. Set env variables or enter them in the credential fields.")
    else:
        with st.spinner("Calling Free Fire API..."):
            api_result = get_ff_account(player_uid, region)
            st.session_state["last_ff_api_response"] = api_result
            # show the raw API result
        st.subheader("API-only result")
        st.json(api_result)
        try:
            blob = json.dumps(api_result, indent=2, ensure_ascii=False)
            st.download_button("Download raw JSON", data=blob, file_name=f"ff_{player_uid}_api.json", mime="application/json")
        except Exception:
            pass

st.markdown("---")
st.caption("Security tip: Do not commit keys to source control. Prefer setting FREEFIRE_USERUID and FREEFIRE_API as env vars.")
