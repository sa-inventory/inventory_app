import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
import datetime

# 2. 데이터베이스 연결
@st.cache_resource
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
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = get_db()

# --- 공통 함수: 기초 코드 가져오기 ---
def get_common_codes(code_key, default_values):
    doc_ref = db.collection("settings").document("codes")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return data.get(code_key, default_values)
    return default_values

# --- 공통 함수: 거래처 목록 가져오기 ---
def get_partners(partner_type=None):
    query = db.collection("partners")
    if partner_type:
        query = query.where("type", "==", partner_type)
    docs = query.stream()
    partners = []
    for doc in docs:
        p = doc.to_dict()
        partners.append(p.get("name"))
    return partners

# --- 공통 함수: 기초 코드가 제품에 사용되었는지 확인 ---
@st.cache_data(ttl=60) # 1분 동안 결과 캐싱
def is_basic_code_used(code_key, name, code):
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
def generate_report_html(title, df, summary_text, options):
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
    
    print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # CSS 템플릿 (중괄호 충돌 방지를 위해 format 사용)
    css = """
        @page {{ margin: {mt}mm {mr}mm {mb}mm {ml}mm; }}
        body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
        h2 {{ text-align: center; margin-bottom: 5px; font-size: {ts}px; }}
        .info {{ text-align: {da}; font-size: {ds}px; margin-bottom: 10px; color: #555; display: {dd}; }}
        table {{ width: 100%; border-collapse: collapse; font-size: {bs}px; }}
        th, td {{ border: 1px solid #444; padding: {pad}px 4px; text-align: center; }}
        th {{ background-color: #f0f0f0; }}
        .summary {{ text-align: right; margin-top: 10px; font-weight: bold; font-size: {bs}px; }}
        @media screen {{ body {{ display: none; }} }}
    """.format(mt=mt, mr=mr, mb=mb, ml=ml, ts=ts, da=da, ds=ds, dd=dd, bs=bs, pad=pad)
    
    html = f"""<html><head><title>{title}</title>
    <style>{css}</style></head><body onload="window.print()">
    <h2>{title}</h2>
    <div class="info">출력일시: {print_now}</div>
    {df.to_html(index=False)}
    <div class="summary">{summary_text}</div>
    </body></html>"""
    
    return html