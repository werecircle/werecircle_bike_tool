# --- Bike Analysis Tool (Patched) ---
# Hardened for: OpenAI v1 SDK (no proxies), Firestore auth, Altair guards,
# single set_page_config, resilient secrets handling, and safer dashboard.

import os
import json
import base64
import random
import tempfile
from io import BytesIO
from datetime import datetime

# --- Streamlit must be the first UI call ---
import streamlit as st
st.set_page_config(page_title="Bike Analysis Tool", layout="wide")

# --------------------------------------------------------------------------------------
# OpenAI client setup (v1 SDK) — force no proxies / no env leakage
# --------------------------------------------------------------------------------------
import httpx
from openai import OpenAI

MODEL_NAME = st.secrets.get("OPENAI_MODEL", "gpt-4o")  # default vision-capable

# httpx: trust_env=False prevents using HTTP(S)_PROXY if present in the environment
_http = httpx.Client(timeout=60, trust_env=False)
client = OpenAI(api_key=st.secrets.get("OPENAI_KEY", ""), http_client=_http)

# --------------------------------------------------------------------------------------
# Firebase / Firestore setup — accept either TOML table or JSON string in secrets
# --------------------------------------------------------------------------------------
import firebase_admin
from firebase_admin import credentials, firestore

FIREBASE_BUCKET = st.secrets.get("FIREBASE_STORAGE_BUCKET", "socs-415712.appspot.com")

if not firebase_admin._apps:
    svc_raw = st.secrets.get("service_account")
    if svc_raw is None:
        st.error("Missing [service_account] in secrets.")
        st.stop()
    if isinstance(svc_raw, str):
        svc_dict = json.loads(svc_raw)
    else:
        # st.secrets returns an AttrDict for tables — convert safely
        svc_dict = json.loads(json.dumps(dict(svc_raw)))

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        json.dump(svc_dict, f)
        cred_path = f.name

    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_BUCKET})
else:
    firebase_admin.get_app(name='[DEFAULT]')

db = firestore.client()

# --------------------------------------------------------------------------------------
# Jinja2 system prompt (with safe fallback if template file is missing)
# --------------------------------------------------------------------------------------
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

SYSTEM_TEMPLATE = "system_message.jinja2"
_system_message = (
    "You are a bike analyst AI. Extract brand tier, condition, e-bike flag, "
    "bike type, frame type, and frame material from a single photo, returning "
    "exactly one label per tool function."
)
try:
    env = Environment(loader=FileSystemLoader("."))
    system_message = env.get_template(SYSTEM_TEMPLATE).render()
except TemplateNotFound:
    system_message = _system_message

# --------------------------------------------------------------------------------------
# Helper utilities
# --------------------------------------------------------------------------------------
DESIRED_FIELDS = [
    'timestamp', 'file_name', 'bike_brand', 'bike_condition',
    'electric_bike', 'bike_type', 'frame_type', 'frame_material', 'goal'
]

import pandas as pd
import altair as alt
import xlsxwriter  # noqa: F401  (used by Excel writer engine)


def encode_image(img_bytes: bytes) -> str:
    return base64.b64encode(img_bytes).decode("utf-8")


def image_name_exists_in_firestore(image_name: str) -> bool:
    try:
        docs = db.collection('bike_data').where('file_name', '==', image_name).limit(1).get()
        return len(docs) > 0
    except Exception as e:
        st.error(f"Failed to check image name in database: {e}", icon='🚨')
        return False


def add_bike_data_to_firestore(bike_data: dict) -> None:
    try:
        db.collection('bike_data').add(bike_data)
        st.success('Complete! Bike data successfully added to database.', icon='✅')
    except Exception as e:
        st.error(f"Failed to add bike data to database: {e}", icon='🚨')


def update_bike_goal_in_firestore(image_name: str, new_goal: str) -> None:
    try:
        docs = db.collection('bike_data').where('file_name', '==', image_name).get()
        for doc in docs:
            doc.reference.update({'goal': new_goal})
    except Exception as e:
        st.error(f"Failed to update bike goal in database: {e}", icon='🚨')


def fetch_bike_data_from_firestore(image_name: str) -> pd.DataFrame:
    try:
        docs = db.collection('bike_data').where('file_name', '==', image_name).limit(1).get()
        for doc in docs:
            data = doc.to_dict()
            df = pd.DataFrame([data])
            return df.reindex(columns=DESIRED_FIELDS)
        return pd.DataFrame(columns=DESIRED_FIELDS)
    except Exception as e:
        st.error(f"Failed to fetch bike data from database: {e}", icon='🚨')
        return pd.DataFrame(columns=DESIRED_FIELDS)


def fetch_all_bike_data_from_firestore() -> pd.DataFrame:
    try:
        all_data = [d.to_dict() for d in db.collection('bike_data').stream()]
        if not all_data:
            return pd.DataFrame(columns=DESIRED_FIELDS)
        df = pd.DataFrame(all_data)
        return df.reindex(columns=DESIRED_FIELDS)
    except Exception as e:
        st.error(f"Failed to fetch all bike data from database: {e}", icon='🚨')
        return pd.DataFrame(columns=DESIRED_FIELDS)


def convert_df_to_excel(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Bike Data')
    return output.getvalue()


def delete_bike_data_from_firestore(image_name: str) -> None:
    try:
        docs = db.collection('bike_data').where('file_name', '==', image_name).get()
        for doc in docs:
            doc.reference.delete()
    except Exception as e:
        st.error(f"Failed to delete bike data from database: {e}", icon='🚨')

# --------------------------------------------------------------------------------------
# Function calling schema for the model
# --------------------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bike_brand",
            "description": (
                "Determine the brand quality tier: one of A-type (high-end), B-type (mid), "
                "C-type (low), or Not specified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "A-type": {"type": "boolean"},
                    "B-type": {"type": "boolean"},
                    "C-type": {"type": "boolean"},
                    "Not specified": {"type": "boolean"}
                },
                "required": ["A-type", "B-type", "C-type", "Not specified"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bike_condition",
            "description": "Return exactly one: Good condition, Moderate condition, Poor condition, Unusable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Good condition": {"type": "boolean"},
                    "Moderate condition": {"type": "boolean"},
                    "Poor condition": {"type": "boolean"},
                    "Unusable": {"type": "boolean"}
                },
                "required": ["Good condition", "Moderate condition", "Poor condition", "Unusable"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "electric_bike",
            "description": "Return exactly one: Electric or Not Electric.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Electric": {"type": "boolean"},
                    "Not Electric": {"type": "boolean"}
                },
                "required": ["Electric", "Not Electric"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bike_type",
            "description": "What type of bike is this? Return exactly one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "City bike": {"type": "boolean"},
                    "Electric city bike": {"type": "boolean"},
                    "Speed pedelec": {"type": "boolean"},
                    "Race bike": {"type": "boolean"},
                    "Electric race bike": {"type": "boolean"},
                    "Mountain bike": {"type": "boolean"},
                    "Electric mountain bike": {"type": "boolean"},
                    "Cargo bike": {"type": "boolean"},
                    "Electric cargo bike": {"type": "boolean"},
                    "Tricycle": {"type": "boolean"},
                    "Kids bike": {"type": "boolean"},
                    "Folding bike": {"type": "boolean"},
                    "Tandem": {"type": "boolean"},
                    "Recumbent bike": {"type": "boolean"},
                    "Longtail bike": {"type": "boolean"},
                    "Electric longtail bike": {"type": "boolean"}
                },
                "required": [
                    "City bike", "Electric city bike", "Speed pedelec", "Race bike", "Electric race bike",
                    "Mountain bike", "Electric mountain bike", "Cargo bike", "Electric cargo bike",
                    "Tricycle", "Kids bike", "Folding bike", "Tandem", "Recumbent bike",
                    "Longtail bike", "Electric longtail bike"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "frame_type",
            "description": "What frame style does the bike have? Return exactly one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Men's bike": {"type": "boolean"},
                    "Women's bike": {"type": "boolean"},
                    "Unisex": {"type": "boolean"}
                },
                "required": ["Men's bike", "Women's bike", "Unisex"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "frame_material",
            "description": "What material is the bike frame made of? Return exactly one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Aluminium": {"type": "boolean"},
                    "Carbon": {"type": "boolean"},
                    "Steel": {"type": "boolean"}
                },
                "required": ["Aluminium", "Carbon", "Steel"]
            }
        }
    }
]

# --------------------------------------------------------------------------------------
# GPT call
# --------------------------------------------------------------------------------------

def call_gpt_model(base64_image: str, image_name: str) -> dict:
    try:
        with st.spinner(f'Generating answers for {image_name}...'):
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_message},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe the bike’s features in the image."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                        ],
                    },
                ],
                tools=TOOLS,
                tool_choice="required",
                temperature=0,
                max_tokens=300,
            )
            msg = response.choices[0].message
            result: dict = {}
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    fn = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    # Ensure exactly one label per tool
                    if fn == 'bike_brand':
                        if not any(args.values()):
                            result[fn] = 'Not specified'
                        else:
                            for key, val in args.items():
                                if val:
                                    result[fn] = key
                                    break
                    else:
                        for key, val in args.items():
                            if val:
                                result[fn] = key
                                break
            else:
                # Fallback for debugging when the model doesn't call tools
                st.warning("Model replied without a tool call; showing raw text for debugging.")
                st.code(getattr(msg, "content", ""))
            return result
    except Exception as e:
        st.error(f"OpenAI error: {e}", icon='🚨')
        return {}

# --------------------------------------------------------------------------------------
# UI helpers
# --------------------------------------------------------------------------------------

def display_results(res_json: dict, name: str, goal: str) -> None:
    res_json['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res_json['file_name'] = name
    res_json['goal'] = goal
    df = pd.DataFrame([res_json]).T
    df.columns = ['Details']
    st.table(df)
    add_bike_data_to_firestore(res_json)


def handle_regeneration(name: str, b64: str, goal: str) -> None:
    delete_bike_data_from_firestore(name)
    new = call_gpt_model(b64, name)
    if new:
        display_results(new, name, goal)
    st.session_state.regenerate[name] = False

# --------------------------------------------------------------------------------------
# Top of page content
# --------------------------------------------------------------------------------------
st.title(":orange[ Bike Analysis Tool ] 🚴")

# Prepare data download
_df_all = fetch_all_bike_data_from_firestore()
_excel_bytes = convert_df_to_excel(_df_all)

st.download_button(
    label="⬇️ Download all bike data as Excel",
    data=_excel_bytes,
    file_name=f"bike_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    mime="application/vnd.ms-excel",
)

st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)

if 'regenerate' not in st.session_state:
    st.session_state.regenerate = {}

uploaded = st.file_uploader("Choose your photos", accept_multiple_files=True)

if uploaded:
    for i in range(0, len(uploaded), 3):
        cols = st.columns(3)
        for col, file in zip(cols, uploaded[i:i+3]):
            with col:
                b64 = encode_image(file.getvalue())
                fname = file.name

                # Goal selector with DB update
                def update_goal():
                    newg = st.session_state[f'goal_{fname}']
                    update_bike_goal_in_firestore(fname, newg)
                    st.session_state[f'goal_update_{fname}'] = newg

                if f'goal_update_{fname}' not in st.session_state:
                    st.session_state[f'goal_update_{fname}'] = ""

                goal = st.selectbox(
                    "What is this bike’s intended use?",
                    ["Resale", "Bike Rental", "Charity shop", "Disassembly", "Scrap"],
                    key=f'goal_{fname}',
                    on_change=update_goal,
                )

                if st.session_state[f'goal_update_{fname}']:
                    st.success(
                        f"Goal for {fname} updated to {st.session_state[f'goal_update_{fname}']}",
                        icon='✅',
                    )
                    st.session_state[f'goal_update_{fname}'] = ""

                # Analyze or show existing
                if not image_name_exists_in_firestore(fname) or st.session_state.regenerate.get(fname, False):
                    if st.session_state.regenerate.get(fname, False):
                        handle_regeneration(fname, b64, goal)
                    else:
                        response = call_gpt_model(b64, fname)
                        with st.expander(f"Show photo for {fname}"):
                            st.image(file.getvalue(), caption=fname, use_column_width=True)
                        if response:
                            display_results(response, fname, goal)

                    st.button(
                        f'🔄 Regenerate for {fname}',
                        key=fname,
                        on_click=lambda name=fname: st.session_state.regenerate.update({name: True}),
                    )
                else:
                    existing = fetch_bike_data_from_firestore(fname)
                    if not existing.empty:
                        st.warning(f"Data for '{fname}' already exists in the database.", icon='⚠️')
                        tbl = existing.T
                        tbl.columns = ['Details']
                        st.table(tbl)
                    st.button(
                        f'🔄 Regenerate for {fname}',
                        key=f'regen_{fname}',
                        on_click=lambda name=fname: st.session_state.regenerate.update({name: True}),
                    )
else:
    # Info & examples
    placeholder = st.empty()
    with placeholder.container():
        st.markdown(
            """
            This tool helps you analyze various features of bicycles using photos. Follow these steps:

            1. 📤 Click the “Choose your photos” button to upload one or more bicycle images.
            2. ⏳ Wait for the AI to analyze each photo and identify features like brand, condition, and type.
            3. 👀 Review the results displayed under each image.

            **Note:** Make sure your photos are clear and high-quality for the best results.
            """
        )
        if os.path.isdir("example_images"):
            imgs = [f for f in os.listdir("example_images") if not f.startswith('.')]
            if len(imgs) >= 4:
                sample = random.sample(imgs, 4)
            else:
                sample = imgs
            cols = st.columns(max(1, len(sample)))
            for idx, col in enumerate(cols):
                if idx < len(sample):
                    path = os.path.join("example_images", sample[idx])
                    if os.path.isfile(path):
                        col.image(path, caption=f"Example {idx+1}", use_column_width=True)

    st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)

    # ---------------------- Analytics Dashboard ----------------------
    def plot_bar_chart(series):
        if series is None or series.empty:
            st.info("No data yet.")
            return
        df = series.rename('Count').reset_index()
        df.columns = ['Date', 'Count']
        try:
            df['Date'] = pd.to_datetime(df['Date'])
        except Exception:
            return st.info("No valid dates to chart yet.")
        df = df.sort_values('Date')
        today = pd.to_datetime('today').normalize()
        ten_days_ago = today - pd.Timedelta(days=10)
        filtered = df[(df['Date'] >= ten_days_ago) & (df['Date'] <= today)]
        if filtered.empty:
            st.info("No recent data to chart yet.")
            return
        chart = alt.Chart(filtered).mark_bar(width=35).encode(
            x=alt.X('Date:T', axis=alt.Axis(format='%d %b')),
            y='Count:Q',
        )
        st.altair_chart(chart, use_container_width=True)

    def plot_pie_chart(data: pd.DataFrame, column: str):
        # Column must exist and have non-empty counts
        if data is None or data.empty or column not in data.columns:
            st.info(f"No data for '{column}' yet.")
            return
        cd = (
            data[column]
            .dropna()
            .astype(str)
            .value_counts()
            .rename_axis(column)
            .reset_index(name="Count")
        )
        if cd.empty:
            st.info(f"No data for '{column}' yet.")
            return
        pie = (
            alt.Chart(cd)
            .transform_joinaggregate(total='sum(Count)')
            .transform_calculate(Percent='datum.Count / datum.total')
            .mark_arc()
            .encode(
                theta=alt.Theta('Count:Q'),
                color=alt.Color(f'{column}:N', legend=None),
                tooltip=[
                    alt.Tooltip(f'{column}:N', title='Category'),
                    alt.Tooltip('Count:Q'),
                    alt.Tooltip('Percent:Q', format='.1%'),
                ],
            )
        )
        st.altair_chart(pie, use_container_width=True)

    st.subheader("Bike Data Dashboard")
    df_all = fetch_all_bike_data_from_firestore()
    if not df_all.empty and 'timestamp' in df_all.columns:
        with pd.option_context('mode.chained_assignment', None):
            try:
                df_all['timestamp'] = pd.to_datetime(df_all['timestamp'], errors='coerce')
                df_all['date'] = df_all['timestamp'].dt.date
            except Exception:
                pass
    counts = df_all.groupby('date').size() if 'date' in df_all.columns else pd.Series(dtype=int)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.write("Number of bikes per day")
        plot_bar_chart(counts)
        st.text(f"Total bikes: {int(counts.sum()) if not counts.empty else 0}")
    with c2:
        st.write("Bike Type")
        plot_pie_chart(df_all, 'bike_type')
    with c3:
        st.write("Electric Bikes")
        plot_pie_chart(df_all, 'electric_bike')
    with c4:
        st.write("Bike Condition")
        plot_pie_chart(df_all, 'bike_condition')

    st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)

    logos = [
        'logo/logo_werecircle.png',
        'logo/logo_mobiel21.png',
        'logo/logo_velo.png',
        'logo/logo_cyclo.png',
        'logo/logo_provelo.png',
    ]
    cols = st.columns(len(logos))
    for col, url in zip(cols, logos):
        if os.path.isfile(url):
            col.image(url, width=150)
