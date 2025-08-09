import streamlit as st
from datetime import time, datetime, timedelta
import streamlit as st
from datetime import time, datetime, timedelta
import itertools
from collections import defaultdict
import firebase_admin
from firebase_admin import credentials, firestore
import json
import os

# アプリのタイトル
st.title("お風呂時間最適化アプリ")

# Firestoreの初期化
if not firebase_admin._apps:
    try:
        # Streamlit CloudのSecretsからJSON文字列を読み込む
        firebase_config_str = st.secrets["firebase"]
        firebase_config = json.loads(firebase_config_str)
    except KeyError:
        st.error("Firebaseの認証情報が設定されていません。Streamlit CloudのSecretsに'firebase'キーを追加してください。")
        st.stop()
    
    cred = credentials.Certificate(firebase_config)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- ヘルパー関数 ---
def time_to_datetime(t):
    """timeオブジェクトをdatetimeオブジェクトに変換する"""
    return datetime.combine(datetime.today(), t)

def datetime_to_time(dt):
    """datetimeオブジェクトをtimeオブジェクトに変換する"""
    return dt.time()

def generate_slots(start, end, duration):
    """指定された時間帯と間隔で入浴スロットを生成する"""
    slots = []
    current = time_to_datetime(start)
    end_dt = time_to_datetime(end)
    while current + duration <= end_dt:
        slots.append((datetime_to_time(current), datetime_to_time(current + duration)))
        current += duration
    return slots

def overlaps(s_start, s_end, nb_start, nb_end):
    """2つの時間帯が重複しているかチェックする"""
    s_start_dt = time_to_datetime(s_start)
    s_end_dt = time_to_datetime(s_end)
    nb_start_dt = time_to_datetime(nb_start)
    nb_end_dt = time_to_datetime(nb_end)
    return not (s_end_dt <= nb_start_dt or s_start_dt >= nb_end_dt)

def find_optimal_schedule(patients, slots, caregivers):
    """すべての組み合わせを試して最適なスケジュールを見つける"""
    best_schedule = None
    max_assigned_patients = -1
    
    num_caregivers = len(caregivers) if caregivers else 1

    for selected_slots in itertools.permutations(slots, len(patients)):
        caregiver_assignments = []
        for i in range(len(patients)):
            caregiver_assignments.append(caregivers[i % num_caregivers])

        current_schedule = []
        assigned_count = 0
        
        for i, patient in enumerate(patients):
            slot_start, slot_end = selected_slots[i]
            assigned_caregiver = caregiver_assignments[i]

            is_conflict = False
            if patient["no_bath_times"]:
                for nb_start, nb_end in patient["no_bath_times"]:
                    if overlaps(slot_start, slot_end, nb_start, nb_end):
                        is_conflict = True
                        break
            
            for s in current_schedule:
                if s["start"] == slot_start and s["caregiver"] == assigned_caregiver:
                    is_conflict = True
                    break

            if not is_conflict:
                current_schedule.append({
                    "name": patient["name"],
                    "start": slot_start,
                    "end": slot_end,
                    "caregiver": assigned_caregiver
                })
                assigned_count += 1
        
        if assigned_count > max_assigned_patients:
            max_assigned_patients = assigned_count
            best_schedule = current_schedule

            if max_assigned_patients == len(patients):
                break

    if best_schedule is not None:
        assigned_patients_names = {s['name'] for s in best_schedule}
        for patient in patients:
            if patient['name'] not in assigned_patients_names:
                best_schedule.append({"name": patient["name"], "start": None, "end": None, "caregiver": None})
    else:
        best_schedule = [{"name": p["name"], "start": None, "end": None, "caregiver": None} for p in patients]

    return best_schedule

# --- Streamlit Session Stateの初期化 ---
if "patients" not in st.session_state:
    st.session_state.patients = []
if "nb_rows" not in st.session_state:
    st.session_state.nb_rows = 1
if "editing_patient_index" not in st.session_state:
    st.session_state.editing_patient_index = None
if "no_bath_time_check" not in st.session_state:
    st.session_state.no_bath_time_check = False
if "settings" not in st.session_state:
    st.session_state.settings = {}

def load_data():
    with st.spinner("データを読み込み中..."):
        doc_ref = db.collection("app_data").document("main_schedule")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            if "patients" in data:
                st.session_state.patients = data["patients"]
            if "settings" in data:
                st.session_state.settings = data["settings"]
                if "bath_start_time" in st.session_state.settings:
                    st.session_state.settings["bath_start_time"] = time.fromisoformat(st.session_state.settings["bath_start_time"])
                if "bath_end_time" in st.session_state.settings:
                    st.session_state.settings["bath_end_time"] = time.fromisoformat(st.session_state.settings["bath_end_time"])
        else:
            st.session_state.patients = []
            st.session_state.settings = {}

def save_data():
    doc_ref = db.collection("app_data").document("main_schedule")
    settings_to_save = st.session_state.settings.copy()
    if "bath_start_time" in settings_to_save:
        settings_to_save["bath_start_time"] = settings_to_save["bath_start_time"].isoformat()
    if "bath_end_time" in settings_to_save:
        settings_to_save["bath_end_time"] = settings_to_save["bath_end_time"].isoformat()
    
    doc_ref.set({
        "patients": st.session_state.patients,
        "settings": settings_to_save
    })
    st.success("データを保存しました！")

if not st.session_state.get("data_loaded", False):
    load_data()
    st.session_state.data_loaded = True

st.sidebar.header("設定")
bath_start_time_setting = st.sidebar.time_input(
    "入浴開始時間",
    value=st.session_state.settings.get("bath_start_time", time(9, 0)),
    key="start_time_input"
)
bath_end_time_setting = st.sidebar.time_input(
    "入浴終了時間",
    value=st.session_state.settings.get("bath_end_time", time(17, 0)),
    key="end_time_input"
)
slot_duration_setting_min = st.sidebar.number_input(
    "一人あたりの入浴時間 (分)",
    min_value=1,
    value=st.session_state.settings.get("slot_duration_min", 30),
    step=1,
    key="duration_input"
)
slot_duration_setting = timedelta(minutes=slot_duration_setting_min)

caregiver_names = st.sidebar.text_area(
    "介助者の名前（改行で区切る）",
    value="\n".join(st.session_state.settings.get("caregivers", ["田中", "山田", "佐藤"])),
    key="caregivers_input"
).splitlines()
caregivers = [name.strip() for name in caregiver_names if name.strip()]

if st.sidebar.button("設定を保存"):
    st.session_state.settings["bath_start_time"] = bath_start_time_setting
    st.session_state.settings["bath_end_time"] = bath_end_time_setting
    st.session_state.settings["slot_duration_min"] = slot_duration_setting_min
    st.session_state.settings["caregivers"] = caregivers
    save_data()

st.info(f"入浴可能時間: {bath_start_time_setting.strftime('%H:%M')} 〜 {bath_end_time_setting.strftime('%H:%M')} (一人 {slot_duration_setting_min} 分)")
if caregivers:
    st.info(f"登録介助者: {', '.join(caregivers)}")
else:
    st.info("介助者が登録されていません。設定で追加してください。")

st.header("患者さん情報入力")

with st.form("patient_form", clear_on_submit=True):
    if st.session_state.editing_patient_index is not None:
        patient_to_edit = st.session_state.patients[st.session_state.editing_patient_index]
        name = st.text_input("患者さんの名前", value=patient_to_edit["name"])
    else:
        name = st.text_input("患者さんの名前")

    st.subheader("入浴不可時間")
    no_bath_times = []
    
    no_bath_time_not_required = st.checkbox("入浴不可時間なし", value=st.session_state.no_bath_time_check, key="no_bath_time_check_form")
    
    if not no_bath_time_not_required:
        for i in range(st.session_state.nb_rows):
            col1, col2 = st.columns(2)
            if st.session_state.editing_patient_index is not None and i < len(st.session_state.patients[st.session_state.editing_patient_index]["no_bath_times"]):
                nb_start_default, nb_end_default = st.session_state.patients[st.session_state.editing_patient_index]["no_bath_times"][i]
            else:
                nb_start_default = time(12, 0)
                nb_end_default = time(13, 0)
            
            with col1:
                nb_start = st.time_input(f"開始時間 #{i+1}", value=nb_start_default, key=f"nb_start_{i}")
            with col2:
                nb_end = st.time_input(f"終了時間 #{i+1}", value=nb_end_default, key=f"nb_end_{i}")
            no_bath_times.append((nb_start, nb_end))

    if st.session_state.editing_patient_index is not None:
        button_text = "患者を更新"
    else:
        button_text = "患者を追加"

    submitted = st.form_submit_button(button_text, type="primary")

    if submitted:
        if not name.strip():
            st.error("名前を入力してください")
        else:
            valid = True
            if not no_bath_time_not_required:
                for s, e in no_bath_times:
                    if time_to_datetime(s) >= time_to_datetime(e):
                        st.error("入浴不可開始時間は終了時間より前にしてください")
                        valid = False
                        break
            
            if valid:
                new_patient_data = {
                    "name": name.strip(),
                    "no_bath_times": no_bath_times if not no_bath_time_not_required else []
                }
                if st.session_state.editing_patient_index is not None:
                    st.session_state.patients[st.session_state.editing_patient_index] = new_patient_data
                    st.success(f"{name.strip()} さんの情報を更新しました")
                else:
                    st.session_state.patients.append(new_patient_data)
                    st.success(f"{name.strip()} さんの情報を追加しました")
                
                st.session_state.editing_patient_index = None
                st.session_state.nb_rows = 1
                st.session_state.no_bath_time_check = False
                save_data()
                st.rerun()

if not st.session_state.get("no_bath_time_check_form", False):
    col1_form, col2_form = st.columns([1, 4])
    with col1_form:
        if st.button("＋不可時間を増やす"):
            st.session_state.nb_rows += 1
            st.session_state.editing_patient_index = None
            st.session_state.no_bath_time_check = False
            st.rerun()

st.markdown("---")
st.header("登録済み患者一覧")
if st.session_state.patients:
    col1, col2, col3, col4 = st.columns([5, 1, 1, 1])
    with col1:
        st.subheader("患者名と不可時間")
    with col2:
        st.subheader("編集")
    with col3:
        st.subheader("削除")
    with col4:
        st.subheader("不可時間削除")
        
    for i, p in enumerate(st.session_state.patients):
        col1, col2, col3, col4 = st.columns([5, 1, 1, 1])
        with col1:
            st.write(f"**{p['name']}**")
            if p["no_bath_times"]:
                for j, (s, e) in enumerate(p["no_bath_times"], 1):
                    st.markdown(f"　- 不可時間#{j}: `{s.strftime('%H:%M')} 〜 {e.strftime('%H:%M')}`")
            else:
                st.markdown("　- なし")
        
        with col2:
            if st.button("編集", key=f"edit_{i}"):
                st.session_state.editing_patient_index = i
                st.session_state.nb_rows = len(st.session_state.patients[i]["no_bath_times"]) if st.session_state.patients[i]["no_bath_times"] else 1
                st.session_state.no_bath_time_check = not st.session_state.patients[i]["no_bath_times"]
                st.rerun()
                
        with col3:
            if st.button("患者削除", key=f"delete_patient_{i}"):
                st.session_state.patients.pop(i)
                st.session_state.editing_patient_index = None
                save_data()
                st.rerun()
        
        with col4:
            if len(p["no_bath_times"]) > 0:
                for j in range(len(p["no_bath_times"])):
                    if st.button(f"不可時間#{j+1}削除", key=f"remove_nb_time_{i}_{j}"):
                        st.session_state.patients[i]["no_bath_times"].pop(j)
                        st.session_state.editing_patient_index = None
                        save_data()
                        st.rerun()
else:
    st.info("患者さんを追加してください。")

st.markdown("---")
if st.session_state.patients:
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("スケジュール作成"):
            st.header("入浴スケジュール")
            
            slots = generate_slots(bath_start_time_setting, bath_end_time_setting, slot_duration_setting)
            
            if not caregivers and st.session_state.patients:
                st.error("介助者が登録されていません。設定で介助者の名前を入力してください。")
            else:
                schedule = find_optimal_schedule(st.session_state.patients, slots, caregivers)
                
                st.subheader("タイムライン表示")
                
                st.markdown("""
                <style>
                .timeline-container {
                    overflow-x: auto;
                    font-size: 12px;
                }
                .schedule-table {
                    border-collapse: collapse;
                    width: 100%;
                    min-width: 1200px;
                }
                .schedule-table th, .schedule-table td {
                    border: 1px solid #ccc;
                    padding: 5px;
                    text-align: center;
                    white-space: nowrap;
                    width: 100px;
                }
                .schedule-table th {
                    background-color: #f0f2f6;
                    position: sticky;
                    left: 0;
                    z-index: 1;
                }
                .schedule-table .time-header {
                    background-color: #e0e0e0;
                    position: sticky;
                    top: 0;
                    z-index: 2;
                }
                .schedule-table .assigned-slot {
                    background-color: #d4edda;
                    color: #155724;
                    font-weight: bold;
                }
                .schedule-table .unavailable-slot {
                    background-color: #f8d7da;
                    color: #721c24;
                }
                </style>
                """, unsafe_allow_html=True)
                
                html = "<div class='timeline-container'><table class='schedule-table'><thead><tr>"
                
                html += "<th>介助者 / 時間</th>"
                for slot_start, _ in slots:
                    html += f"<th class='time-header'>{slot_start.strftime('%H:%M')}</th>"
                html += "</tr></thead><tbody>"
                
                for caregiver in caregivers:
                    html += f"<tr><th>{caregiver}</th>"
                    for slot_start, slot_end in slots:
                        assigned_patient = None
                        for s in schedule:
                            if s['start'] == slot_start and s['caregiver'] == caregiver:
                                assigned_patient = s
                                break
                        
                        if assigned_patient:
                            html += f"<td class='assigned-slot'>{assigned_patient['name']}</td>"
                        else:
                            html += "<td></td>"
                    html += "</tr>"
                
                unassigned_patients = [s['name'] for s in schedule if s['start'] is None]
                if unassigned_patients:
                    html += f"<tr><th>割り当て不可</th>"
                    html += f"<td colspan='{len(slots)}' class='unavailable-slot'>{'、'.join(unassigned_patients)}</td></tr>"
                
                html += "</tbody></table></div>"
                st.markdown(html, unsafe_allow_html=True)

                st.markdown("---")
                st.subheader("リスト表示")
                for s in schedule:
                    if s["start"] and s["end"]:
                        st.success(f"**{s['name']}**（介助者: {s['caregiver']}）: {s['start'].strftime('%H:%M')} 〜 {s['end'].strftime('%H:%M')}")
                    else:
                        st.warning(f"**{s['name']}**: 割り当て可能な時間がありません")
    
    with col2:
        if st.button("すべてのデータをリセット"):
            st.session_state.patients = []
            st.session_state.nb_rows = 1
            st.session_state.editing_patient_index = None
            st.session_state.no_bath_time_check = False
            save_data()
            st.rerun()
