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
if not firebase_admin._apps:
    try:
        # 방법 1: Streamlit Cloud의 비밀 금고(Secrets)에 키가 있는지 확인
        # (로컬에서는 이 줄에서 에러가 발생하여 except로 넘어갑니다)
        if "FIREBASE_KEY" in st.secrets:
            # 비밀 금고에 있는 텍스트 키를 가져와서 사용
            key_dict = json.loads(st.secrets["FIREBASE_KEY"])
            cred = credentials.Certificate(key_dict)
        else:
            cred = credentials.Certificate("serviceAccountKey.json")
    except:
        # 방법 2: 에러가 나면(로컬 환경이면) 내 컴퓨터에 있는 파일 사용
        cred = credentials.Certificate("serviceAccountKey.json")
        
    firebase_admin.initialize_app(cred)

db = firestore.client()

# 3. [왼쪽 사이드바] 상품 등록 기능
with st.sidebar:
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

# 4. [메인 화면] 재고 목록 보여주기
st.header("📊 현재 재고 목록")

# 새로고침 버튼 (누르면 최신 데이터 불러옴)
if st.button("목록 새로고침"):
    st.rerun()

# 데이터베이스에서 모든 데이터 가져오기 (최신순 정렬)
docs = db.collection("inventory").order_by("date", direction=firestore.Query.DESCENDING).stream()

# 가져온 데이터를 표로 만들기 좋게 정리
data_list = []
for doc in docs:
    item = doc.to_dict()
    data_list.append({
        "상품명": item.get("name"),
        "카테고리": item.get("category"),
        "재고수량": f"{item.get('stock')} 개",
        "등록일시": item.get("date").strftime("%Y-%m-%d %H:%M") if item.get("date") else ""
    })

# 화면에 표(Table) 그리기
if data_list:
    st.table(data_list)
else:
    st.info("아직 등록된 상품이 없습니다. 왼쪽 사이드바에서 등록해주세요.")
