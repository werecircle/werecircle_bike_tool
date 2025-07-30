import base64
import streamlit as st
import openai
from openai import OpenAI
import json
from jinja2 import Environment, FileSystemLoader
import pandas as pd
from datetime import datetime
import re
import firebase_admin
from firebase_admin import credentials, firestore
import pandas as pd
from io import BytesIO
import os
import random
import xlsxwriter
import altair as alt

tools = [
    {
        "type": "function",
        "function": {
            "name": "fiets_merk",
            "description": "Wat is de originele kwaliteit van de fiets in de afbeelding? Controleer de naam van het fietsmerk vermeld op het fietskader indien zichtbaar. Plaats vervolgens 'true' bij één van de volgende categorieen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "A-merk": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een kwalitatief fietsmerk. (Trek, Canyon, BMC, ...)"
                    },
                    "B-merk": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een B-merk  (Btwin, Triban, ...)"
                    },
                    "C-merk": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een C-merk. (Supermarkt fiets, City Star, ...)"
                    },
                    "Niet zichtbaar": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als alle voorgaande parameters niet 'true' is."
                    }
                },
                "required": [
                    "A-merk",
                    "B-merk",
                    "C-merk",
                    "Niet zichtbaar"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fiets_kwaliteit",
            "description": "Wat is de huidige staat van de fiets? Analyseer de huidige staat van de fiets, lijkt de fiets klaar voor gebruik of zijn er duidelijk herstellingen nodig? Plaats vervolgens 'true' bij één van de volgende categorieen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Goede staat": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als er geen zichtbare schade is en geen herstellingen nodig zijn."
                    },
                    "Matige staat": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als er kleine zichtbare schade is en kleine goedkopere herstellingen zijn mogelijk."
                    },
                    "Slechte staat": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als er zichtbaar veel schadeis en grote herstellingen nodig zijn die zowel geld zullen kosten als tijd."
                    },
                    "Onbruikbaar": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als de fiets niet meer bruikbaar is om te gebruiken door duidelijke problemen zoals: breuk in het kader, ... ."
                    }
                },
                "required": [
                    "Goede staat",
                    "Matige staat",
                    "Slechte staat",
                    "Onbruikbaar"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "elektrisch",
            "description": "Is deze fiets elektrisch aangedreven? Plaats vervolgens 'true' bij één van de volgende categorieen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Elektrisch": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een elektrisch aangedreven fiets. Een elektrische fiets is te herkennen aan specifieke kenmerken: (1) Motor: Er zijn drie veelvoorkomende typen motoren: middenmotor (geïnstalleerd bij de trapas in het midden van het frame, vaak te vinden bij de pedalen), achterwielmotor (te vinden in het midden van het achterwiel), en voorwielmotor. (2) Batterij: Een duidelijk kenmerk van e-bikes is de batterij, die geïntegreerd kan zijn in het frame of aan de zadelbuis. Soms is een dikkere framebuis zichtbaar om de batterij te verbergen. Zelden wordt de batterij op de framebuis gemonteerd. Vaak vind je de batterij ook onder het bagagerek van de fiets of op het bagagerek, en deze is meestal rechthoekig en groter dan andere fietsonderdelen. (3) Display en bedieningselementen: Aanwezig op het stuur."
                    },
                    "Niet Elektrisch": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als de fiets niet elektrisch aangedreven is."
                    }
                },
                "required": [
                    "Elektrisch",
                    "Niet Elektrisch"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fiets_type",
            "description": "Welk type fiets is het? Plaats vervolgens 'true' bij één van de volgende categorieen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Stadsfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Stadsfiets. Kenmerkend door een rechte of licht gebogen zitpositie, vaak voorzien van een bagagedrager aan de achterkant. Het frame is robuust, en de fiets is uitgerust met spatborden en soms een kettingkast voor dagelijks gebruik."
                    },
                    "Electrische Stadsfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Electrische Stadsfiets. Kenmerkend door een rechte of licht gebogen zitpositie, vaak voorzien van een bagagedrager aan de achterkant. Het frame is robuust, en de fiets is uitgerust met spatborden en soms een kettingkast voor dagelijks gebruik. Electrisch aangedreven te herkennen aan de baterij en motor werwerkt in de fiets."
                    },
                    "Speedpedelec": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Speedpedelec. Een elektrische fiets met een krachtigere motor en een grotere batterij, zichtbaar op het frame. Heeft vaak een sportievere zitpositie en is uitgerust met hoogwaardige remmen en versnellingen om hoge snelheden te ondersteunen. Meestal een zichtbare motor in het achterwiel of aan de trapas en bredere frame buizen voor de batterij in te verwerken."
                    },
                    "Racefiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Racefiets. Herkenbaar aan het lichte frame, dunne banden, en het kenmerkende stuur dat omlaag en naar voren buigt voor een aerodynamische houding. De zitpositie is voorovergebogen om snelheid en efficiëntie te bevorderen."
                    },
                    "E-Racefiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een E-Racefiets. Vergelijkbaar met een gewone race fiets is een e-recefiets kenmerkend aan het iets dikkere fram met daarn vaak de baterij verwerkt. Deze fiets heeft een middenmotor geinstaleerd aan de trapas en , dunne banden, en het kenmerkende stuur dat omlaag en naar voren buigt voor een aerodynamische houding. De zitpositie is voorovergebogen om snelheid en efficiëntie te bevorderen."
                    },
                    "Mountainbike": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Mountainbike. Uitgerust met brede banden met diep profiel voor grip op onverharde wegen, een stevig frame, en vaak vering aan de voor- of achterkant. De zitpositie is ontworpen voor controle over ruig terrein."
                    },
                    "E-mountenbike": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een E-mountenbike. Is een Electrisch aangedreven mountenbike. Deze mountenbike heeft dezelfde kenmerken als een gewone mountenbike maar heeft vaak een ingebouwde motor en baterij verwerkt in het kader."
                    },
                    "Bakfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Bakfiets. Herkenbaar aan de grote bak aan de voorzijde van de fiets, gebruikt voor het vervoeren van goederen of kinderen. Het frame strekt zich uit naar voren om de bak te ondersteunen, wat de fiets een unieke vorm geeft."
                    },
                    "Elektrische - Bakfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Elektrische - Bakfiets. Herkenbaar aan de grote bak aan de voorzijde van de fiets, gebruikt voor het vervoeren van goederen of kinderen. Het frame strekt zich uit naar voren om de bak te ondersteunen, wat de fiets een unieke vorm geeft. Omwille van de zware lasten die ermee vervoerd kunnen worden, is dit type fiets dikwijls voorzien van elektrische ondersteuning. Dat hoeft echter niet per se het geval te zijn. Vaak met een middenmotor onder de trapas en een batterij die op –in het frame is verwerkt."
                    },
                    "Driewieler": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Driewieler. Kenmerkend door de drie wielen, twee achter en één voor, of andersom, wat zorgt voor stabiliteit en ondersteuning. Vaak ontworpen voor volwassenen of kinderen met een lage zitpositie tussen de achterwielen."
                    },
                    "Kinderfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Kinderfiets. Kleiner in omvang met een lagere zitpositie, vaak kleurrijk versierd en mogelijk uitgerust met zijwieltjes voor evenwicht. Het frame en de componenten zijn aangepast aan jonge rijders."
                    },
                    "Plooifiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Plooifiets. Herkenbaar aan het scharnier in het frame waarmee de fiets opgevouwen kan worden voor opslag of vervoer. Kleinder dan gewone fietsen, met kleinere wielen en een compacte bouw."
                    },
                    "Tandem": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Tandem. Lang en herkenbaar door de twee (of meer) zitplaatsen achter elkaar, ontworpen voor meerdere rijders. Het frame is verlengd om de extra zitplaatsen te accommoderen."
                    },
                    "Ligfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Ligfiets. Heeft een lage zitpositie met de benen vooruit om te trappen, wat zorgt voor een opvallend profiel en een comfortabele rijpositie. Het frame en de zitpositie zijn ontworpen voor efficiëntie en comfort."
                    },
                    "Longtail": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Longtail. Uitgerust met een verlengd achterdeel van het frame, bedoeld voor het dragen van extra lading of passagiers. Het ziet eruit als een traditionele fiets, maar met een opvallend langere achterkant"
                    },
                    "Elektrische longtail": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een Elektrische longtail. Uitgerust met een verlengd achterdeel van het frame, bedoeld voor het dragen van extra lading of passagiers. Het ziet eruit als een traditionele fiets, maar met een opvallend langere achterkant. Omwille van de zware lasten die ermee vervoerd kunnen worden, is dit type fiets dikwijls voorzien van elektrische ondersteuning. Dat hoeft echter niet per se het geval te zijn. De motor is vaak te vinden ingebouwd in de trapas of een achterwiel motor."
                    },
                },
                "required": [
                    "Stadsfiets",
                    "Electrische Stadsfiets",
                    "Speedpedelec",
                    "Racefiets",
                    "E-Racefiets",
                    "Mountainbike",
                    "E-mountenbike",
                    "Bakfiets",
                    "Elektrische - Bakfiets",
                    "Driewieler",
                    "Kinderfiets",
                    "Plooifiets",
                    "Tandem",
                    "Ligfiets",
                    "Longtail",
                    "Elektrische longtail"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fietskader_type",
            "description": "Welk type kader heeft de fiest op de afbeelding? Plaats vervolgens 'true' bij één van de volgende categorieen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Herenfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een heren fiets. Een fiets ontworpen met een rechte of nagenoeg horizontale bovenbuis die loopt van de zadel naar het stuur. Kenmerken: (1) Rechte bovenbuis: De bovenbuis loopt parallel aan de grond. (2) Hogere instap: Het vereist een hogere beenlift om op de fiets te stappen. (3) Stijf frame: Ontworpen voor extra duurzaamheid en om de traditionele mannelijke gebruiker te accommoderen."
                    },
                    "Damesfiets": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een dames fiets. Een fiets met een lage of geheel ontbrekende bovenbuis, waardoor een lagere instap mogelijk is voor gemakkelijker op- en afstappen. Kenmerken: (1) Lage of ontbrekende bovenbuis: De bovenbuis is schuin geplaatst of ontbreekt, wat zorgt voor een lagere instap. (2) Sierlijke lijnen: Het frame kan elegantere en sierlijke lijnen hebben. (3) Ontworpen voor rokken/jurken: Traditioneel ontworpen om het rijden in rokken of jurken te vergemakkelijken."
                    },
                    "Unisex": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een unisex fiets. Een fietskader ontworpen om toegankelijk te zijn voor alle geslachten, met een mix van kenmerken uit heren- en damesfietsen voor algemeen comfort en gebruiksgemak. Kenmerken: (1) Schuine bovenbuis: De bovenbuis heeft een lichte helling, maar is hoger dan bij de typische damesfiets, wat een evenwicht biedt tussen toegankelijkheid en framestijfheid. (2) Middelhoge instap: Gemakkelijker op- en afstappen dan bij een herenfiets, zonder de extreem lage instap van de meeste damesfietsen. (3) Neutrale styling: Het ontwerp en de kleuren zijn vaak neutraal, gericht op brede aantrekkelijkheid."
                    }
                },
                "required": [
                    "Herenfiets",
                    "Damesfiets", 
                    "Unisex"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fietskader_materiaal",
            "description": "Welk type materiaal heeft het kader van de fiest op de afbeelding? Plaats vervolgens 'true' bij één van de volgende categorieen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Aluminium": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een alluminium fietskader. Lichtgewicht, roestbestendig metaal dat vaak gebruikt wordt voor het vervaardigen van moderne fietsframes. Visuele kenmerken: (1) Afwerking: Vaak glanzend of met een duidelijke metallic look. Kan ook mat zijn als het gecoat is. (2) Lasnaden: Grotere, meer zichtbare lasnaden bij de verbindingen dan bij carbon. (3) Buizen: De buisvormen kunnen variëren, maar zijn vaak oversized voor extra sterkte zonder significant gewicht toe te voegen. Toepassing: Wordt veel gebruikt in racefietsen, mountainbikes, en stadsfietsen vanwege de goede balans tussen gewicht, sterkte, en kosten."
                    },
                    "Carbon": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een carbon fietsframe. Een lichtgewicht en sterk composietmateriaal dat gebruikt wordt voor high-end fietsframes. Visuele kenmerken: (1) Afwerking: Kan variëren van glanzend tot mat, vaak met een diepere, 'rijkere' uitstraling dan aluminium. (2) Lasnaden: Carbon frames hebben geen zichtbare lasnaden omdat de stukken koolstofvezel in mallen worden gelijmd en geperst. (3) Buizen: Buizen kunnen unieke vormen hebben, met complexe curven die specifiek zijn ontworpen voor prestaties en comfort, moeilijk te repliceren met metalen. Toepassing: Veel gebruikt in racefietsen, mountainbikes en triathlonfietsen voor professioneel en competitief gebruik, waar gewichtsbesparing en stijfheid essentieel zijn."
                    },
                    "Staal": {
                        "type": "boolean",
                        "description": "Antwoord hier 'true' als het gaat om een stalen fietsframe. Traditioneel materiaal voor fietsframes, bekend om zijn duurzaamheid, veerkracht en reparatiegemak. Visuele kenmerken: (1) Afwerking: Heeft een unieke textuur die lijkt op geweven stof onder de lak. De afwerking kan variëren van hoogglans tot mat. (2) Lasnaden: Fijnere lasnaden dan bij aluminium, soms bijna naadloos bij hoogwaardige frames. (3) Buizen: Buizen zijn vaak dunner dan bij aluminium of carbon frames, met een klassieke, tijdloze uitstraling. Toepassing: Wordt gebruikt voor tourfietsen, vintage racefietsen, en custom fietsen. Staal is populair bij liefhebbers die waarde hechten aan comfort, duurzaamheid, en het esthetische aspect."
                    }
                },
                "required": [
                    "Aluminium",
                    "Carbon", 
                    "Staal"
                ]
            }
        }
    }
]



if not firebase_admin._apps:
    service_account_info = st.secrets["service_account"]
    cred = credentials.Certificate(json.loads(service_account_info))
    firebase_admin.initialize_app(cred, {'storageBucket': 'socs-415712.appspot.com'})
else:
    firebase_admin.get_app(name='[DEFAULT]')

db = firestore.client()

file_loader = FileSystemLoader('.')
env = Environment(loader=file_loader)
template = env.get_template('system_message.jinja2')
system_message = template.render()

def encode_image(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def image_name_exists_in_firestore(image_name):
    try:
        fiets_gegevens_ref = db.collection('fiets gegevens')
        query_ref = fiets_gegevens_ref.where('foto_naam', '==', image_name).limit(1).get()
        return len(query_ref) > 0
    except Exception as e:
        st.error(f'Failed to check image name in database: {e}', icon='🚨')
        return False

def add_bike_data_to_firestore(bike_data):
    try:
        fiets_gegevens_ref = db.collection('fiets gegevens')
        fiets_gegevens_ref.add(bike_data)
        st.success('Compleet! Fietsgegevens succesvol toegevoegd aan database.', icon='✅')
    except Exception as e:
        st.error(f'Failed to add bike data to database: {e}', icon='🚨')

def update_bike_goal_in_firestore(image_name, new_goal):
    try:
        fiets_gegevens_ref = db.collection('fiets gegevens')
        query_ref = fiets_gegevens_ref.where('foto_naam', '==', image_name).get()
        for doc in query_ref:
            doc.reference.update({'doel': new_goal})
    except Exception as e:
        st.error(f'Failed to update bike goal in database: {e}', icon='🚨')

def fetch_bike_data_from_firestore(image_name):
    try:
        fiets_gegevens_ref = db.collection('fiets gegevens')
        query_ref = fiets_gegevens_ref.where('foto_naam', '==', image_name).limit(1).get()

        for doc in query_ref:
            data = doc.to_dict()
            df = pd.DataFrame([data])
            desired_order = ['datum', 'foto_naam', 'fiets_merk', 'fiets_kwaliteit', 'elektrisch', 'fiets_type', 'fietskader_type', 'fietskader_materiaal', 'doel']
            df = df[desired_order]
            return df

        return pd.DataFrame(columns=desired_order)
    except Exception as e:
        st.error(f'Failed to fetch bike data from database: {e}', icon='🚨')
        return pd.DataFrame(columns=desired_order)
    
def fetch_all_bike_data_from_firestore():
    all_data = []
    try:
        fiets_gegevens_ref = db.collection('fiets gegevens')
        docs = fiets_gegevens_ref.stream()

        for doc in docs:
            data = doc.to_dict()
            all_data.append(data)

        df = pd.DataFrame(all_data)
        desired_order = ['datum', 'foto_naam', 'fiets_merk', 'fiets_kwaliteit', 'elektrisch', 'fiets_type', 'fietskader_type', 'fietskader_materiaal', 'doel']
        df = df.reindex(columns=desired_order)
        
        return df
    except Exception as e:
        st.error(f'Failed to fetch all bike data from database: {e}', icon='🚨')
        return pd.DataFrame(columns=desired_order)

def convert_df_to_excel(df):
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Bike Data')
    writer.close()
    processed_data = output.getvalue()
    return processed_data

def delete_bike_data_from_firestore(image_name):
    try:
        fiets_gegevens_ref = db.collection('fiets gegevens')
        docs = fiets_gegevens_ref.where('foto_naam', '==', image_name).get()

        for doc in docs:
            doc.reference.delete()

    except Exception as e:
        st.error(f'Failed to delete bike data from database: {e}', icon='🚨')

def call_gpt_model(base64_image, image_name):
    try:
        with st.spinner(f'Antwoorden genereren voor {image_name}...'):
          
            client = OpenAI(api_key=st.secrets['OPENAI_KEY'])

            response = client.chat.completions.create(
              model="gpt-4o",
              messages=[
                {"role": "system", "content": system_message},
                {
                  "role": "user",
                  "content": [
                    {"type": "text", "text": f"Beschrijf de features van de fiets in de afbeelding?"},
                    {
                      "type": "image_url",
                      "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                      },
                    },
                  ],
                }
              ],
              tools=tools,
              temperature=0,
              max_tokens=300,
            )

            response_message = response.choices[0].message
                
            result_as_dict = {}
            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    print(f'name: {function_name}, arguments: {arguments}')
                    if function_name == 'fiets_merk':
                        # Check if all values are False and set 'Niet zichtbaar' to True if so
                        if not any(arguments.values()):
                            result_as_dict[function_name] = 'Niet zichtbaar'
                        else:
                            for key, value in arguments.items():
                                if value:
                                    result_as_dict[function_name] = key
                                    break
                    else:
                        for key, value in arguments.items():
                            if value:
                                result_as_dict[function_name] = key
                                break
        return result_as_dict

    except Exception as e:
        st.error(f"Er is een fout opgetreden: {e}", icon='🚨')
        return {}

# Main UI logic

st.set_page_config(page_title="Fiets Analyse Tool", page_icon=":bike:", layout="wide")
st.title(":orange[Fiets Analyse Tool] 🚴")
info_page_placeholder = st.empty()

uploaded_files = st.file_uploader("Kies je foto's", accept_multiple_files=True)

df_all_bike_data = fetch_all_bike_data_from_firestore()  # Fetch all bike data
excel_data = convert_df_to_excel(df_all_bike_data)  # Convert DataFrame to Excel

btn = st.download_button(
    label="⬇️ Download alle fietsgegevens als Excel",
    data=excel_data,
    file_name=f"fiets_gegevens_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    mime="application/vnd.ms-excel"
)

st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)

analytics_page_placeholder = st.empty()

# Initialiseer sessiestatus om regeneratieverzoeken bij te houden
if 'regenerate' not in st.session_state:
    st.session_state.regenerate = {}

def display_results(response_json, uploaded_file_name, selected_goal):
    response_json['datum'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    response_json['foto_naam'] = uploaded_file_name
    response_json['doel'] = selected_goal  # Add the selected goal to the results
    df = pd.DataFrame([response_json])
    desired_order = ['datum', 'foto_naam', 'fiets_merk', 'fiets_kwaliteit', 'elektrisch', 'fiets_type', 'fietskader_type', 'fietskader_materiaal', 'doel']
    df = df[desired_order].T
    df.columns = ['Details']
    st.table(df)
    add_bike_data_to_firestore(response_json)

def handle_regeneration(uploaded_file_name, base64_image, selected_goal):
    delete_bike_data_from_firestore(uploaded_file_name)
    response_json = call_gpt_model(base64_image, uploaded_file_name)
    if response_json:
        display_results(response_json, uploaded_file_name, selected_goal)
    st.session_state.regenerate[uploaded_file_name] = False

if uploaded_files:
    for i in range(0, len(uploaded_files), 3):
        cols = st.columns(3)
        for col, uploaded_file in zip(cols, uploaded_files[i:i+3]):
            with col:
                base64_image = encode_image(uploaded_file.getvalue())
                file_name = uploaded_file.name

                def update_goal(file_name):
                    new_goal = st.session_state[f'goal_{file_name}']
                    update_bike_goal_in_firestore(file_name, new_goal)
                    st.session_state[f'goal_update_{file_name}'] = new_goal

                if f'goal_update_{file_name}' not in st.session_state:
                    st.session_state[f'goal_update_{file_name}'] = ""

                goal = st.selectbox(
                    "Welk doel zal deze fiets dienen?",
                    ["Verkoop", "Fietsverhuur", "Kringwinkel", "Afbraak", "Schroot"],
                    key=f'goal_{file_name}',
                    on_change=lambda file_name=file_name: update_goal(file_name)
                )

                if st.session_state[f'goal_update_{file_name}']:
                    st.success(f'Doel voor {file_name} bijgewerkt naar {st.session_state[f"goal_update_{file_name}"]}.', icon='✅')
                    st.session_state[f'goal_update_{file_name}'] = ""

                if not image_name_exists_in_firestore(file_name) or st.session_state.regenerate.get(file_name, False):
                    if st.session_state.regenerate.get(file_name, False):
                        handle_regeneration(file_name, base64_image, goal)
                    else:
                        try:
                            response_json = call_gpt_model(base64_image, file_name)
                            with st.expander(f"Toon foto voor {file_name}"):
                                st.image(uploaded_file.getvalue(), caption=file_name, use_column_width=True)
                            if response_json:
                                display_results(response_json, file_name, goal)
                        except Exception as e:
                            st.error(f'Er is iets mis gegaan. Probeer opnieuw: {e}', icon='🚨')

                    st.button(f'🔄 Genereer opnieuw voor {file_name}', key=file_name, on_click=lambda fn=file_name: st.session_state.regenerate.update({fn: True}))
                else:
                    existing_data = fetch_bike_data_from_firestore(file_name)
                    if not existing_data.empty:
                        st.warning(f"De gegevens voor '{file_name}' bevinden zich al in de database.", icon='⚠️')
                        existing_data = existing_data.T
                        existing_data.columns = ['Details']
                        st.table(existing_data)

                    if st.button(f'🔄 Genereer opnieuw voor {file_name}', key=f'regenerate_{file_name}', on_click=lambda fn=file_name: st.session_state.regenerate.update({fn: True})):
                        handle_regeneration(file_name, base64_image, goal)

else:
    with info_page_placeholder.container():
        st.markdown("""
            Deze tool helpt je bij het analyseren van verschillende kenmerken van fietsen aan de hand van foto's. Hieronder volgen de stappen om de tool te gebruiken:

            1. 📤 Klik op de "Kies je foto's" knop om één of meerdere foto's van fietsen te uploaden.
            2. ⏳ Wacht totdat de AI de fiets op de foto analyseert en kenmerken zoals merk, kwaliteit, en type identificeert.
            3. 👀 Bekijk de resultaten die onder elke foto worden getoond.

            **Let op:** Zorg ervoor dat de foto's duidelijk en van goede kwaliteit zijn voor de beste resultaten.
        """)

        image_files = os.listdir("example_images")
        selected_images = random.sample(image_files, 4)

        cols = st.columns(4)
        for i, col in enumerate(cols):
            image_path = os.path.join("example_images", selected_images[i])
            col.image(image_path, caption=f"Voorbeeld {i+1}", use_column_width=True)

        st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)

    with analytics_page_placeholder.container():

        def plot_bar_chart(data):
            data_series = pd.Series(data, name='Count').reset_index()
            data_series.columns = ['Date', 'Count']
            data_series['Date'] = pd.to_datetime(data_series['Date'])
            data_series = data_series.sort_values(by='Date')
            today = pd.to_datetime('today').normalize()
            ten_days_ago = today - pd.Timedelta(days=10)
            filtered_data = data_series[(data_series['Date'] >= ten_days_ago) & (data_series['Date'] <= today)]
            chart = alt.Chart(filtered_data).mark_bar(width=35, color='#EE7C58').encode(
                x=alt.X('Date:T', axis=alt.Axis(format='%d %b')),
                y='Count:Q'
            )
            st.altair_chart(chart, use_container_width=True)

        def plot_pie_chart(data, column):
            chart_data = data[column].value_counts().reset_index()
            chart_data.columns = [column, 'Count']
            chart_data = chart_data.sort_values(by='Count', ascending=True)
            color_palette = [
                '#EE7C58', '#EED2C1', '#F8A488', '#D46B50', '#A15641',
                '#F7BBA6', '#FFD1C1', '#C0604D', '#FFC1A6', '#B24D3E'
            ]
            num_segments = len(chart_data)
            if num_segments > len(color_palette):
                color_palette *= (num_segments // len(color_palette)) + 1
            chart_data['Color'] = color_palette[:num_segments]
            total_count = chart_data['Count'].sum()
            pie_chart = alt.Chart(chart_data).mark_arc().encode(
                theta=alt.Theta(field="Count", type="quantitative", sort='descending'),
                color=alt.Color(field='Color', type='nominal', scale=None),
                order=alt.Order('Count:Q', sort='descending'),
                tooltip=[
                    alt.Tooltip(column, title=column),
                    alt.Tooltip('Count', title='Count'),
                    alt.Tooltip('PercentOfTotal:Q', title='Percentage', format='.1%')
                ]
            ).transform_calculate(
                PercentOfTotal="datum.Count / " + str(total_count)
            )
            st.altair_chart(pie_chart, use_container_width=True)

        st.subheader("Fiets Data Dashboard")

        df_all_bike_data = fetch_all_bike_data_from_firestore()
        df_all_bike_data['datum'] = pd.to_datetime(df_all_bike_data['datum'])
        df_all_bike_data['hour'] = df_all_bike_data['datum'].dt.hour
        df_all_bike_data['date'] = df_all_bike_data['datum'].dt.date
        bike_counts_per_day = df_all_bike_data.groupby('date').size()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.write("Aantal fietsen per dag")
            plot_bar_chart(bike_counts_per_day)
            total_bikes = bike_counts_per_day.sum()
            st.text(f"Totaal aantal fietsen: {total_bikes}")

        with col2:
            st.write("Type Fiets")
            plot_pie_chart(df_all_bike_data, 'fiets_type')

        with col3:
            st.write("Elektrische Fietsen")
            plot_pie_chart(df_all_bike_data, 'elektrisch')

        with col4:
            st.write("Fietskwaliteit")
            plot_pie_chart(df_all_bike_data, 'fiets_kwaliteit')
            
        st.markdown('<hr style="border:1px solid #F8A488;">', unsafe_allow_html=True)
      
        image_urls = [
            'logo/logo_werecircle.png',
            'logo/logo_mobiel21.png',
            'logo/logo_velo.png',
            'logo/logo_cyclo.png',
            'logo/logo_provelo.png',
        ]

        cols = st.columns(len(image_urls))
        for col, url in zip(cols, image_urls):
            col.image(url, width=150)