import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
import datetime
import pandas as pd
import urllib.request
import urllib.parse

# 2. 데이터베이스 연결
def get_db():
    if not firebase_admin._apps:
        cred = None
        # 방법 1: Streamlit Cloud의 비밀 금고(Secrets) 시도
        try:
            if "FIREBASE_KEY" in st.secrets:
                secret_val = st.secrets["FIREBASE_KEY"]
                if isinstance(secret_val, str):
                    key_dict = json.loads(secret_val)
                else:
                    key_dict = dict(secret_val)
                cred = credentials.Certificate(key_dict)
        except:
            pass

        # 방법 2: 로컬 환경이거나 비밀 금고가 없으면 내 컴퓨터 파일 사용
        if cred is None:
            import os
            if os.path.exists("serviceAccountKey.json"):
                cred = credentials.Certificate("serviceAccountKey.json")
            else:
                st.error("🔥 Firebase 인증 키를 찾을 수 없습니다. Streamlit Cloud의 Secrets에 'FIREBASE_KEY'를 설정해주세요.")
                st.stop()
            
        firebase_admin.initialize_app(cred)
    return firestore.client()

# --- 공통 함수: 기초 코드 가져오기 ---
@st.cache_data(ttl=300) # 5분 캐싱
def get_common_codes(code_key, default_values):
    db = get_db()
    doc_ref = db.collection("settings").document("codes")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return data.get(code_key, default_values)
    return default_values

# --- 공통 함수: 거래처 목록 가져오기 ---
@st.cache_data(ttl=300) # 5분 캐싱
def get_partners(partner_type=None):
    db = get_db()
    query = db.collection("partners")
    if partner_type:
        query = query.where("type", "==", partner_type)
    docs = query.stream()
    partners = []
    for doc in docs:
        p = doc.to_dict()
        partners.append(p.get("name"))
    return partners

# --- 공통 함수: 거래처 정보 Map 가져오기 (상세 정보 포함) ---
@st.cache_data(ttl=300) # 5분 캐싱
def get_partners_map():
    db = get_db()
    docs = db.collection("partners").stream()
    return {doc.to_dict().get('name'): doc.to_dict() for doc in docs}

# [NEW] 공통 함수: 제품 목록 가져오기 (캐싱)
@st.cache_data(ttl=300)
def get_products_list():
    db = get_db()
    docs = db.collection("products").order_by("product_code").stream()
    return [doc.to_dict() for doc in docs]

# [NEW] 공통 함수: 제직기 목록 가져오기 (캐싱)
@st.cache_data(ttl=300)
def get_machines_list():
    db = get_db()
    docs = db.collection("machines").order_by("machine_no").stream()
    return [doc.to_dict() for doc in docs]

# [NEW] 공통 함수: 사용자 목록 가져오기 (캐싱)
@st.cache_data(ttl=300)
def get_users_list():
    db = get_db()
    docs = db.collection("users").stream()
    return [doc.to_dict() for doc in docs]

# --- 공통 함수: 기초 코드가 제품에 사용되었는지 확인 ---
@st.cache_data(ttl=60) # 1분 동안 결과 캐싱
def is_basic_code_used(code_key, name, code):
    db = get_db()
    """지정된 기초 코드가 'products' 컬렉션에서 사용되었는지 확인합니다."""
    query = None
    if code_key == "product_types":
        query = db.collection("products").where("product_type", "==", name).limit(1)
    elif code_key == "yarn_types_coded":
        query = db.collection("products").where("yarn_type", "==", name).limit(1)
    elif code_key == "size_codes":
        query = db.collection("products").where("size", "==", name).limit(1)
    elif code_key == "weight_codes":
        try:
            weight_val = int(code)
            query = db.collection("products").where("weight", "==", weight_val).limit(1)
        except (ValueError, TypeError):
            return False 
    
    return len(list(query.stream())) > 0 if query else False

# --- 공통 함수: 인쇄용 HTML 생성 ---
def generate_report_html(title, df, summary_text, options, chart_html=""):
    """
    데이터프레임과 옵션을 받아 인쇄용 HTML 문자열을 생성합니다.
    f-string과 CSS 중괄호 충돌 방지를 위해 format()을 사용합니다.
    """
    # 옵션 추출 (기본값 설정)
    mt = options.get('mt', 15)
    mr = options.get('mr', 15)
    mb = options.get('mb', 15)
    ml = options.get('ml', 15)
    ts = options.get('ts', 24)
    bs = options.get('bs', 11)
    pad = options.get('pad', 6)
    da = options.get('da', 'right')
    ds = options.get('ds', 12)
    dd = options.get('dd', 'block')
    bo = options.get('bo', 1.0)
    bi = options.get('bi', 0.5)
    
    print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # CSS 템플릿 (중괄호 충돌 방지를 위해 format 사용)
    css = """
        @page {{ margin: {mt}mm {mr}mm {mb}mm {ml}mm; }}
        body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
        h2 {{ text-align: center; margin-bottom: 5px; font-size: {ts}px; }}
        .info {{ text-align: {da}; font-size: {ds}px; margin-bottom: 10px; color: #555; display: {dd}; }}
        table {{ width: 100%; border-collapse: collapse; font-size: {bs}px; border: {bo}px solid #444; }}
        th, td {{ border: {bi}px solid #444; padding: {pad}px 4px; text-align: center; }}
        th {{ background-color: #f0f0f0; }}
        .summary {{ text-align: right; margin-top: 10px; font-weight: bold; font-size: {bs}px; }}
        @media screen {{ body {{ display: none; }} }}
    """.format(mt=mt, mr=mr, mb=mb, ml=ml, ts=ts, da=da, ds=ds, dd=dd, bs=bs, pad=pad, bo=bo, bi=bi)
    
    html = f"""<html><head><title>{title}</title>
    <style>{css}</style></head><body onload="window.print()">
    <h2>{title}</h2>
    <div class="info">출력일시: {print_now}</div>
    {chart_html}
    {df.to_html(index=False)}
    <div class="summary">{summary_text}</div>
    </body></html>"""
    
    return html

# --- 공통 함수: 기초 코드 관리 UI ---

# 이름-코드 쌍 관리 함수
def manage_code_with_code(code_key, default_list, label):
    db = get_db()
    current_list = get_common_codes(code_key, default_list)

    st.markdown(f"##### 현재 등록된 {label}")
    # 이전 버전 호환을 위해 딕셔너리 형태만 필터링
    current_list_dicts = [item for item in current_list if isinstance(item, dict)]
    if current_list_dicts:
        # 코드 기준 오름차순 정렬
        current_list_dicts.sort(key=lambda x: x.get('code', ''))
        df = pd.DataFrame(current_list_dicts, columns=['name', 'code'])
    else:
        df = pd.DataFrame(columns=['name', 'code'])

    selection = st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"df_{code_key}"
    )

    st.divider()

    # --- 수정 / 삭제 (항목 선택 시) ---
    if selection.selection.rows:
        idx = selection.selection.rows[0]
        sel_row = df.iloc[idx]
        sel_name = sel_row['name']
        sel_code = sel_row['code']

        is_used = is_basic_code_used(code_key, sel_name, sel_code)

        if is_used:
            st.subheader(f"'{sel_name}' 정보")
            st.warning("이 항목은 제품 등록에 사용되어 수정 및 삭제가 불가능합니다.")
            st.text_input("명칭", value=sel_name, disabled=True)
            st.text_input("코드", value=sel_code, disabled=True)
        else:
            # 수정 폼
            with st.form(key=f"edit_{code_key}"):
                st.subheader(f"'{sel_name}' 수정")
                new_name = st.text_input("명칭", value=sel_name)
                new_code = st.text_input("코드", value=sel_code)

                if st.form_submit_button("수정 저장"):
                    if new_name and new_code:
                        # 새 명칭이 다른 항목에서 이미 사용 중인지 확인
                        is_name_taken = any(item.get('name') == new_name for item in current_list_dicts if item.get('name') != sel_name)
                        if is_name_taken:
                            st.error(f"'{new_name}'은(는) 이미 존재하는 명칭입니다.")
                        else:
                            for item in current_list_dicts:
                                if item.get('name') == sel_name: # 기존 이름으로 항목 찾기
                                    item['name'] = new_name # 이름 업데이트
                                    item['code'] = new_code # 코드 업데이트
                                    break
                            db.collection("settings").document("codes").set({code_key: current_list_dicts}, merge=True)
                            st.success("수정되었습니다.")
                            st.rerun()

            # 삭제 기능
            st.subheader(f"'{sel_name}' 삭제")
            if st.button("이 항목 삭제하기", type="primary", key=f"del_btn_{code_key}"):
                updated_list = [item for item in current_list_dicts if item['name'] != sel_name]
                db.collection("settings").document("codes").set({code_key: updated_list}, merge=True)
                st.success("삭제되었습니다.")
                st.rerun()

    # --- 추가 (항목 미선택 시) ---
    else:
        st.subheader(f"신규 {label} 추가")
        if not df.empty:
            st.info("목록에서 항목을 선택하면 수정 또는 삭제할 수 있습니다.")

        with st.form(key=f"add_{code_key}", clear_on_submit=True):
            c1, c2 = st.columns(2)
            new_name = c1.text_input("명칭")
            new_code = c2.text_input("코드")
            if st.form_submit_button("추가"):
                if new_name and new_code:
                    if any(item.get('name') == new_name for item in current_list_dicts):
                        st.error("이미 존재하는 명칭입니다.")
                    else:
                        current_list_dicts.append({'name': new_name, 'code': new_code})
                        db.collection("settings").document("codes").set({code_key: current_list_dicts}, merge=True)
                        st.success("추가되었습니다.")
                        st.rerun()
                else:
                    st.warning("명칭과 코드를 모두 입력해주세요.")

# 단순 리스트 관리 함수
def manage_code(code_key, default_list, label):
    db = get_db()
    current_list = get_common_codes(code_key, default_list)
    st.markdown(f"##### 현재 등록된 {label}")
    if current_list: st.dataframe(pd.DataFrame(current_list, columns=["명칭"]), width="stretch", hide_index=True)
    else: st.info("등록된 항목이 없습니다.")
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        new_val = st.text_input(f"추가할 {label} 입력", key=f"new_{code_key}")
        if st.button(f"추가", key=f"btn_add_{code_key}"):
            if new_val and new_val not in current_list:
                current_list.append(new_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("추가되었습니다."); st.rerun()
    with c2:
        del_val = st.selectbox(f"삭제할 {label} 선택", ["선택하세요"] + current_list, key=f"del_{code_key}")
        if st.button(f"삭제", key=f"btn_del_{code_key}"):
            if del_val != "선택하세요":
                current_list.remove(del_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("삭제되었습니다."); st.rerun()

# --- 공통 함수: 주소 검색 API 호출 ---
def search_address_api(keyword, page=1):
    db = get_db()
    """
    행정안전부 도로명주소 검색 API를 호출하여 결과를 반환합니다.
    """
    # DB에서 API 키 가져오기
    doc = db.collection("settings").document("company_info").get()
    api_key = doc.to_dict().get("juso_api_key", "") if doc.exists else ""
    
    if not api_key:
        return None, None, "API 키가 등록되지 않았습니다. [시스템관리 > 회사정보 관리]에서 키를 입력해주세요."
    
    try:
        # API 호출
        encoded_keyword = urllib.parse.quote(keyword)
        api_url = f"https://business.juso.go.kr/addrlink/addrLinkApi.do?confmKey={api_key}&currentPage={page}&countPerPage=10&keyword={encoded_keyword}&resultType=json"
        
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req) as response:
            res_body = response.read()
            json_data = json.loads(res_body.decode('utf-8'))
            
            results = json_data.get('results', {})
            common = results.get('common', {})
            
            if common.get('errorCode') != '0':
                return None, None, f"API 오류: {common.get('errorMessage')}"
            
            juso_list = results.get('juso', [])
            return juso_list, common, None
            
    except Exception as e:
        return None, None, f"검색 중 오류 발생: {str(e)}"

# --- 공통 함수: 비밀번호 유효성 검사 ---
def validate_password(password):
    """
    비밀번호 정책 검사:
    1. 4자리 이상 12자리 이하
    2. 영문과 숫자만 허용 (특수문자 불가)
    3. 동일한 문자/숫자 4번 연속 금지 (예: 1111, aaaa)
    4. 연속된 문자/숫자 4자리 이상 금지 (예: 1234, abcd)
    """
    if not (4 <= len(password) <= 12):
        return False, "비밀번호는 4자리 이상 12자리 이하여야 합니다."
    
    if not password.isalnum():
        return False, "비밀번호는 영문과 숫자만 사용할 수 있습니다."
    
    for i in range(len(password) - 3):
        # 동일 문자 4번 연속
        if password[i] == password[i+1] == password[i+2] == password[i+3]:
            return False, "동일한 문자를 4번 이상 연속해서 사용할 수 없습니다."
        # 연속된 문자 (ASCII 코드 기준)
        if ord(password[i+1]) == ord(password[i]) + 1 and ord(password[i+2]) == ord(password[i]) + 2 and ord(password[i+3]) == ord(password[i]) + 3:
            return False, "연속된 문자나 숫자를 4자리 이상 사용할 수 없습니다."
            
    return True, ""

# [NEW] 사용자 설정 저장/로드 함수
def save_user_settings(user_id, key, value):
    db = get_db()
    if not user_id: return
    try:
        # settings 필드 내에 key: value 형태로 저장 (Dot notation for nested update)
        db.collection("users").document(user_id).update({f"settings.{key}": value})
    except:
        # 문서가 없거나 settings 필드가 없을 경우 set with merge
        db.collection("users").document(user_id).set({"settings": {key: value}}, merge=True)

def load_user_settings(user_id, key, default_value):
    db = get_db()
    if not user_id: return default_value
    try:
        doc = db.collection("users").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            settings = data.get("settings", {})
            val = settings.get(key)
            if val is not None:
                if isinstance(default_value, dict) and isinstance(val, dict):
                    # Merge to keep defaults for missing keys
                    merged = default_value.copy()
                    merged.update(val)
                    return merged
                return val
    except:
        pass
    return default_value