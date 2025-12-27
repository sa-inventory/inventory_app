import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import json

# 1. 화면 기본 설정 (제목 등)
st.set_page_config(page_title="우리 가게 재고관리", layout="wide")
st.title("재고 관리 시스템")

# 2. 데이터베이스 연결 (아까 받은 열쇠 사용)
# 이미 연결되어 있다면 건너뛰고, 안 되어 있을 때만 연결합니다.
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        # 방법 1: Streamlit Cloud의 비밀 금고(Secrets)에 키가 있는지 확인
        if "FIREBASE_KEY" in st.secrets:
            secret_val = st.secrets["FIREBASE_KEY"]
            if isinstance(secret_val, str):
                key_dict = json.loads(secret_val)
            else:
                key_dict = dict(secret_val)
            cred = credentials.Certificate(key_dict)
        else:
            # 방법 2: 로컬 환경이거나 비밀 금고가 없으면 내 컴퓨터 파일 사용
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = get_db()

# --- 로그인 기능 추가 ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["role"] = None

if not st.session_state["logged_in"]:
    st.subheader("로그인")
    login_id = st.text_input("아이디", placeholder="admin 또는 guest")
    login_pw = st.text_input("비밀번호", type="password", placeholder="1234")
    
    if st.button("로그인"):
        # 예시를 위해 하드코딩된 계정 사용 (실제로는 DB에서 확인 권장)
        if login_id == "admin" and login_pw == "1234":
            st.session_state["logged_in"] = True
            st.session_state["role"] = "admin"
            st.rerun()
        elif login_id == "guest" and login_pw == "1234":
            st.session_state["logged_in"] = True
            st.session_state["role"] = "guest"
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호를 확인하세요.")
    st.stop()  # 로그인 전에는 아래 내용을 보여주지 않음

# 3. [왼쪽 사이드바] 상품 등록 기능
with st.sidebar:
    st.write(f"환영합니다, **{st.session_state['role']}**님!")
    if st.button("로그아웃"):
        st.session_state["logged_in"] = False
        st.session_state["role"] = None
        st.rerun()
    st.divider()

    # 관리자(admin)에게만 등록 화면 보여주기
    if st.session_state["role"] == "admin":
        st.header("📝 상품 등록")
        name = st.text_input("상품명")
        category = st.selectbox("카테고리", ["전자제품", "의류", "식품", "기타"])
        stock = st.number_input("수량", min_value=0, step=1)
        
        if st.button("저장하기"):
            if name:
                # Firestore 데이터베이스에 저장하는 코드
                doc_ref = db.collection("inventory").add({
                    "name": name,
                    "category": category,
                    "stock": stock,
                    "date": datetime.datetime.now()
                })
                st.success(f"'{name}' 저장 완료!")
                # 저장 후 화면을 바로 새로고침합니다.
                st.rerun()
            else:
                st.error("상품명을 입력해주세요.")
    else:
        st.info("게스트 계정은 재고 조회만 가능합니다.")

# 4. [메인 화면] 재고 목록 보여주기
st.header("📊 현재 재고 목록")

# 새로고침 버튼 (누르면 최신 데이터 불러옴)
if st.button("목록 새로고침"):
    st.rerun()

# 데이터베이스에서 모든 데이터 가져오기 (최신순 정렬)
docs = list(db.collection("inventory").order_by("date", direction=firestore.Query.DESCENDING).stream())

# 가져온 데이터를 표로 만들기 좋게 정리
if not docs:
    st.info("아직 등록된 상품이 없습니다. 왼쪽 사이드바에서 등록해주세요.")

# 헤더 (표의 머리글)
col1, col2, col3, col4 = st.columns([3, 1, 2, 2])
col1.write("**상품명 (카테고리)**")
col2.write("**수량**")
col3.write("**등록일**")
col4.write("**관리**")

for doc in docs:
    item = doc.to_dict()
    doc_id = doc.id
    
    with st.container():
        c1, c2, c3, c4 = st.columns([3, 1, 2, 2])
        c1.write(f"{item.get('name')} ({item.get('category')})")
        c2.write(f"{item.get('stock')}개")
        c3.write(item.get('date').strftime("%Y-%m-%d") if item.get('date') else "")
        
        with c4:
            if st.session_state["role"] == "admin":
                # 수량 조절 및 삭제 버튼
                btn1, btn2, btn3 = st.columns(3)
                if btn1.button("➕", key=f"add_{doc_id}"):
                    db.collection("inventory").document(doc_id).update({"stock": item.get('stock') + 1})
                    st.rerun()
                if btn2.button("➖", key=f"sub_{doc_id}"):
                    if item.get('stock') > 0:
                        db.collection("inventory").document(doc_id).update({"stock": item.get('stock') - 1})
                        st.rerun()
                if btn3.button("🗑️", key=f"del_{doc_id}", help="삭제"):
                    db.collection("inventory").document(doc_id).delete()
                    st.rerun()
            else:
                st.caption("조회 전용")
    st.divider()
