import base64
import streamlit as st
import openai
from openai import OpenAI

# --- OpenAI diagnostics (Checks if the OpenAI connectivity is good or bad, and lists available models) ---
import streamlit as st
from openai import OpenAI

def check_openai_connectivity():
    try:
        client = OpenAI(api_key=st.secrets["OPENAI_KEY"])  # don't pass proxies here
        models = client.models.list()
        ids = [m.id for m in models.data][:10]
        st.success(f"OpenAI reachable ✅  Visible models: {ids}")
        return True
    except Exception as e:
        st.error(f"OpenAI check failed ❌  {type(e).__name__}: {e}")
        st.info(
            "If you see 401 → bad/missing key; 429 → quota/billing; "
            "404/400 model not found → update the model name you use."
        )
        return False

with st.sidebar:
    if st.button("🔎 Check OpenAI connectivity"):
        check_openai_connectivity()
        
import json
from jinja2 import Environment, FileSystemLoader
import pandas as pd
from datetime import datetime
import re
import firebase_admin
from firebase_admin import credentials, firestore
from io import BytesIO
import os
import random
import xlsxwriter
import altair as alt

# --- GPT Function Definitions ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "bike_brand",
            "description": (
                "What is the original quality tier of the bike in the image? "
                "Check the brand name on the frame if visible, then return 'true' "
                "for exactly one of the following categories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "A-type": {
                        "type": "boolean",
                        "description": "Return true for a high-end brand (e.g. Trek, Canyon, BMC)."
                    },
                    "B-type": {
                        "type": "boolean",
                        "description": "Return true for a mid-tier brand (e.g. Btwin, Triban)."
                    },
                    "C-type": {
                        "type": "boolean",
                        "description": "Return true for a low-tier brand (e.g. supermarket bike, City Star)."
                    },
                    "Not specified": {
                        "type": "boolean",
                        "description": "Return true if none of the above apply or the brand is not visible."
                    }
                },
                "required": ["A-type", "B-type", "C-type", "Not specified"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bike_condition",
            "description": (
                "What is the current condition of the bike? Analyze visible damage or maintenance needs, "
                "then return 'true' for exactly one of the following categories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "Good condition": {
                        "type": "boolean",
                        "description": "Return true if no visible damage and ready to use."
                    },
                    "Moderate condition": {
                        "type": "boolean",
                        "description": "Return true if minor damage that requires inexpensive repairs."
                    },
                    "Poor condition": {
                        "type": "boolean",
                        "description": "Return true if significant damage requiring costly repairs."
                    },
                    "Unusable": {
                        "type": "boolean",
                        "description": "Return true if the bike is not rideable (e.g. broken frame)."
                    }
                },
                "required": ["Good condition", "Moderate condition", "Poor condition", "Unusable"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "electric_bike",
            "description": (
                "Is this bike electrically powered? Return 'true' for exactly one of the following categories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "Electric": {
                        "type": "boolean",
                        "description": (
                            "Return true if it is electrically assisted. Look for a motor (hub or mid-drive), "
                            "battery pack, and control display on the handlebars."
                        )
                    },
                    "Not Electric": {
                        "type": "boolean",
                        "description": "Return true if the bike has no electrical assistance."
                    }
                },
                "required": ["Electric", "Not Electric"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bike_type",
            "description": "What type of bike is this? Return 'true' for exactly one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "City bike": {
                        "type": "boolean",
                        "description": "Return true if a standard upright city bike with fenders and rack."
                    },
                    "Electric city bike": {
                        "type": "boolean",
                        "description": "Return true if a city bike with electric assistance."
                    },
                    "Speed pedelec": {
                        "type": "boolean",
                        "description": "Return true if a high-speed electric bike with robust motor and battery."
                    },
                    "Race bike": {
                        "type": "boolean",
                        "description": "Return true if a lightweight bike with drop handlebars for speed."
                    },
                    "Electric race bike": {
                        "type": "boolean",
                        "description": "Return true if a race-style bike with an integrated motor and battery."
                    },
                    "Mountain bike": {
                        "type": "boolean",
                        "description": "Return true if a bike with suspension and knobby tires for off-road."
                    },
                    "Electric mountain bike": {
                        "type": "boolean",
                        "description": "Return true if a mountain bike with electric assistance."
                    },
                    "Cargo bike": {
                        "type": "boolean",
                        "description": "Return true if a bike with a large cargo box or platform."
                    },
                    "Electric cargo bike": {
                        "type": "boolean",
                        "description": "Return true if a cargo bike with motor assistance."
                    },
                    "Tricycle": {
                        "type": "boolean",
                        "description": "Return true if a three-wheeled bike."
                    },
                    "Kids bike": {
                        "type": "boolean",
                        "description": "Return true if a bicycle sized for children."
                    },
                    "Folding bike": {
                        "type": "boolean",
                        "description": "Return true if a bike with a folding hinge in the frame."
                    },
                    "Tandem": {
                        "type": "boolean",
                        "description": "Return true if a bike with two or more seats in line."
                    },
                    "Recumbent bike": {
                        "type": "boolean",
                        "description": "Return true if a bike where the rider reclines with legs forward."
                    },
                    "Longtail bike": {
                        "type": "boolean",
                        "description": "Return true if a bike with an extended rear rack capable of carrying more load."
                    },
                    "Electric longtail bike": {
                        "type": "boolean",
                        "description": "Return true if a longtail bike with electric assistance."
                    }
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
            "description": "What frame style does the bike have? Return 'true' for exactly one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Men's bike": {
                        "type": "boolean",
                        "description": "Return true if it has a horizontal top tube typical of men's frames."
                    },
                    "Women's bike": {
                        "type": "boolean",
                        "description": "Return true if it has a lowered or step-through frame design."
                    },
                    "Unisex": {
                        "type": "boolean",
                        "description": "Return true if it has a sloping top tube combining features of both."
                    }
                },
                "required": ["Men's bike", "Women's bike", "Unisex"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "frame_material",
            "description": "What material is the bike frame made of? Return 'true' for exactly one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Aluminium": {
                        "type": "boolean",
                        "description": "Return true if the frame is aluminum: lightweight, rust-resistant metal."
                    },
                    "Carbon": {
                        "type": "boolean",
                        "description": "Return true if the frame is carbon fiber: lightweight composite material."
                    },
                    "Steel": {
                        "type": "boolean",
                        "description": "Return true if the frame is steel: durable metal with classic look."
                    }
                },
                "required": ["Aluminium", "Carbon", "Steel"]
            }
        }
    }
]

import json, tempfile

# --- Firebase Initialization ---
if not firebase_admin._apps:
    svc = st.secrets["service_account"]

    # Normalize to a plain dict
    if isinstance(svc, str):
        svc_info = json.loads(svc)  # when secrets stored as a JSON string
    else:
        # AttrDict -> dict (and ensure JSON-serializable)
        svc_info = json.loads(json.dumps(dict(svc)))

    # Write to a temp file because credentials.Certificate reliably accepts a file path
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        json.dump(svc_info, f)
        temp_path = f.name

    cred = credentials.Certificate(temp_path)
    firebase_admin.initialize_app(
        cred,
        {
            "storageBucket": st.secrets.get("FIREBASE_STORAGE_BUCKET", "socs-415712.appspot.com"),
        },
    )
else:
    firebase_admin.get_app(name='[DEFAULT]')

db = firestore.client()

# --- Jinja2 System Prompt ---
file_loader = FileSystemLoader('.')
env = Environment(loader=file_loader)
template = env.get_template('system_message.jinja2')
system_message = template.render()

# --- Helper Functions ---
def encode_image(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def image_name_exists_in_firestore(image_name):
    try:
        collection = db.collection('bike_data')
        query_ref = collection.where('file_name', '==', image_name).limit(1).get()
        return len(query_ref) > 0
    except Exception as e:
        st.error(f'Failed to check image name in database: {e}', icon='🚨')
        return False

def add_bike_data_to_firestore(bike_data):
    try:
        collection = db.collection('bike_data')
        collection.add(bike_data)
        st.success('Complete! Bike data successfully added to database.', icon='✅')
    except Exception as e:
        st.error(f'Failed to add bike data to database: {e}', icon='🚨')

def update_bike_goal_in_firestore(image_name, new_goal):
    try:
        collection = db.collection('bike_data')
        docs = collection.where('file_name', '==', image_name).get()
        for doc in docs:
            doc.reference.update({'goal': new_goal})
    except Exception as e:
        st.error(f'Failed to update bike goal in database: {e}', icon='🚨')

def fetch_bike_data_from_firestore(image_name):
    try:
        collection = db.collection('bike_data')
        docs = collection.where('file_name', '==', image_name).limit(1).get()
        for doc in docs:
            data = doc.to_dict()
            df = pd.DataFrame([data])
            desired = ['timestamp', 'file_name', 'bike_brand', 'bike_condition',
                       'electric_bike', 'bike_type', 'frame_type', 'frame_material', 'goal']
            return df[desired]
        return pd.DataFrame(columns=desired)
    except Exception as e:
        st.error(f'Failed to fetch bike data from database: {e}', icon='🚨')
        return pd.DataFrame(columns=desired)

def fetch_all_bike_data_from_firestore():
    all_data = []
    try:
        collection = db.collection('bike_data')
        for doc in collection.stream():
            all_data.append(doc.to_dict())
        df = pd.DataFrame(all_data)
        desired = ['timestamp', 'file_name', 'bike_brand', 'bike_condition',
                   'electric_bike', 'bike_type', 'frame_type', 'frame_material', 'goal']
        return df.reindex(columns=desired)
    except Exception as e:
        st.error(f'Failed to fetch all bike data from database: {e}', icon='🚨')
        return pd.DataFrame(columns=desired)

def convert_df_to_excel(df):
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Bike Data')
    writer.close()
    return output.getvalue()

def delete_bike_data_from_firestore(image_name):
    try:
        collection = db.collection('bike_data')
        docs = collection.where('file_name', '==', image_name).get()
        for doc in docs:
            doc.reference.delete()
    except Exception as e:
        st.error(f'Failed to delete bike data from database: {e}', icon='🚨')

# --- GPT Call ---
def call_gpt_model(base64_image, image_name):
    try:
        with st.spinner(f'Generating answers for {image_name}...'):
            client = OpenAI(api_key=st.secrets['OPENAI_KEY'])
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe the bike’s features in the image."},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                tools=tools,
                temperature=0,
                max_tokens=300
            )
            msg = response.choices[0].message
            result = {}
            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    fn = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    # Handle bike_brand default
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
            return result
    except Exception as e:
        st.error(f"An error occurred: {e}", icon='🚨')
        return {}

# --- Streamlit UI ---
st.set_page_config(page_title="Bike Analysis Tool", layout="wide")
st.title(":orange[ Bike Analysis Tool ] 🚴")

# Prepare data download
df_all = fetch_all_bike_data_from_firestore()
excel_bytes = convert_df_to_excel(df_all)

st.download_button(
    label="⬇️ Download all bike data as Excel",
    data=excel_bytes,
    file_name=f"bike_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    mime="application/vnd.ms-excel"
)

st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)

if 'regenerate' not in st.session_state:
    st.session_state.regenerate = {}

def display_results(res_json, name, goal):
    res_json['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    res_json['file_name'] = name
    res_json['goal'] = goal
    df = pd.DataFrame([res_json]).T
    df.columns = ['Details']
    st.table(df)
    add_bike_data_to_firestore(res_json)

def handle_regeneration(name, b64, goal):
    delete_bike_data_from_firestore(name)
    new = call_gpt_model(b64, name)
    if new:
        display_results(new, name, goal)
    st.session_state.regenerate[name] = False

uploaded = st.file_uploader("Choose your photos", accept_multiple_files=True)

if uploaded:
    for i in range(0, len(uploaded), 3):
        cols = st.columns(3)
        for col, file in zip(cols, uploaded[i:i+3]):
            with col:
                b64 = encode_image(file.getvalue())
                fname = file.name

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
                    on_change=update_goal
                )

                if st.session_state[f'goal_update_{fname}']:
                    st.success(
                        f'Goal for {fname} updated to {st.session_state[f"goal_update_{fname}"]}.',
                        icon='✅'
                    )
                    st.session_state[f'goal_update_{fname}'] = ""

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
                        on_click=lambda name=fname: st.session_state.regenerate.update({name: True})
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
                        on_click=lambda name=fname: st.session_state.regenerate.update({name: True})
                    )
else:
    # Info & examples
    placeholder = st.empty()
    with placeholder.container():
        st.markdown("""
            This tool helps you analyze various features of bicycles using photos. Follow these steps:

            1. 📤 Click the “Choose your photos” button to upload one or more bicycle images.
            2. ⏳ Wait for the AI to analyze each photo and identify features like brand, condition, and type.
            3. 👀 Review the results displayed under each image.

            **Note:** Make sure your photos are clear and high-quality for the best results.
        """)
        imgs = os.listdir("example_images")
        sample = random.sample(imgs, 4)
        cols = st.columns(4)
        for idx, col in enumerate(cols):
            path = os.path.join("example_images", sample[idx])
            col.image(path, caption=f"Example {idx+1}", use_column_width=True)

    st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)

    # Analytics Dashboard
    dashboard = st.empty()
    with dashboard.container():
        def plot_bar_chart(data):
            series = pd.Series(data, name='Count').reset_index()
            series.columns = ['Date', 'Count']
            series['Date'] = pd.to_datetime(series['Date'])
            series = series.sort_values('Date')
            today = pd.to_datetime('today').normalize()
            ten_days_ago = today - pd.Timedelta(days=10)
            filtered = series[(series['Date'] >= ten_days_ago) & (series['Date'] <= today)]
            chart = alt.Chart(filtered).mark_bar(width=35).encode(
                x=alt.X('Date:T', axis=alt.Axis(format='%d %b')),
                y='Count:Q'
            )
            st.altair_chart(chart, use_container_width=True)


        def plot_pie_chart(data: pd.DataFrame, column: str):
            # Guard rails: column present and non-empty counts
            if column not in data.columns or data[column].dropna().empty:
                st.info(f"No data for '{column}' yet.")
                return

            cd = (
                data[column]
                    .dropna()
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
                        alt.Tooltip('Percent:Q', format='.1%')
                    ]
                )
            )
            st.altair_chart(pie, use_container_width=True)

        st.subheader("Bike Data Dashboard")
        df_all = fetch_all_bike_data_from_firestore()
        df_all['timestamp'] = pd.to_datetime(df_all['timestamp'])
        df_all['date'] = df_all['timestamp'].dt.date
        counts = df_all.groupby('date').size()

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.write("Number of bikes per day")
            plot_bar_chart(counts)
            st.text(f"Total bikes: {counts.sum()}")
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
            col.image(url, width=150)
