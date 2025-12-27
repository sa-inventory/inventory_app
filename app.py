import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import json
import pandas as pd

# 1. 화면 기본 설정 (제목 등)
st.set_page_config(page_title="타올 생산 현황 관리", layout="wide")
st.title("🏭 세안타올 생산관리 현황")

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
    
    # 메뉴 선택 기능 추가
    st.subheader("작업 메뉴")
    menu = st.radio("이동할 메뉴를 선택하세요", 
        ["발주서접수", "제직현황", "염색현황", "봉제현황", "출고현황", "현재고현황"])

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "발주서접수":
    st.header("📑 발주서 접수")
    
    # 탭을 사용하여 '등록'과 '조회' 화면 분리
    tab1, tab2 = st.tabs(["📝 신규 발주 등록", "🔍 발주 현황 조회 및 관리"])
    
    with tab1:
        if st.session_state["role"] == "admin":
            with st.form("order_form"):
                st.subheader("기본 발주 정보")
                c1, c2, c3 = st.columns(3)
                order_date = c1.date_input("발주접수일", datetime.date.today())
                customer = c2.text_input("발주처 (거래처명)")
                delivery_req_date = c3.date_input("납품요청일", datetime.date.today() + datetime.timedelta(days=7))

                st.subheader("제품 상세 정보")
                c1, c2, c3, c4 = st.columns(4)
                name = c1.text_input("제품명 (타올 종류)")
                category = c2.selectbox("구분", ["세면타올", "바스타올", "핸드타올", "비치타올", "기타"])
                weaving_type = c3.selectbox("제직타입", ["30수 연사", "40수 코마사", "무지", "자카드", "기타"])
                yarn_type = c4.text_input("사종", placeholder="예: 최고급 면사")
                
                c1, c2, c3, c4 = st.columns(4)
                color = c1.text_input("색상")
                weight = c2.number_input("중량(g)", min_value=0, step=10)
                size = c3.text_input("사이즈", placeholder="예: 40x80")
                stock = c4.number_input("수량(장)", min_value=0, step=10)

                st.subheader("납품 및 기타 정보")
                c1, c2, c3 = st.columns(3)
                delivery_to = c1.text_input("납품처")
                delivery_contact = c2.text_input("납품 연락처")
                delivery_address = c3.text_input("납품 주소")
                
                note = st.text_area("특이사항")
                
                submitted = st.form_submit_button("발주 등록")
                if submitted:
                    if name and customer:
                        # Firestore에 저장할 데이터 딕셔너리 생성
                        doc_data = {
                            "date": datetime.datetime.combine(order_date, datetime.time.min), # 날짜 형식을 datetime으로 변환
                            "customer": customer,
                            "delivery_req_date": str(delivery_req_date),
                            "name": name,
                            "category": category,
                            "weaving_type": weaving_type,
                            "yarn_type": yarn_type,
                            "color": color,
                            "weight": weight,
                            "size": size,
                            "stock": stock,
                            "delivery_to": delivery_to,
                            "delivery_contact": delivery_contact,
                            "delivery_address": delivery_address,
                            "note": note,
                            "status": "발주접수" # 초기 상태
                        }
                        db.collection("inventory").add(doc_data)
                        st.success(f"'{customer}' - '{name}' 발주가 정상적으로 접수되었습니다!")
                        st.rerun()
                    else:
                        st.error("제품명과 발주처는 필수 입력 항목입니다.")
        else:
            st.info("관리자만 발주를 등록할 수 있습니다. 옆의 '발주 현황 조회' 탭을 이용해주세요.")

    with tab2:
        st.write("조건을 설정하여 발주 내역을 조회합니다.")
        
        # 필터링 기능
        c1, c2, c3 = st.columns(3)
        filter_status = c1.multiselect("진행 상태", ["발주접수", "제직", "염색", "봉제", "출고"], default=["발주접수", "제직", "염색", "봉제"])
        filter_customer = c2.text_input("발주처 검색")
        
        # 데이터 가져오기
        docs = db.collection("inventory").order_by("date", direction=firestore.Query.DESCENDING).stream()
        
        # 데이터를 리스트로 변환
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            # 날짜 객체를 보기 좋게 문자열로 변환
            if 'date' in d and d['date']:
                d['date'] = d['date'].strftime("%Y-%m-%d")
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            
            # 필터 적용
            if filter_status:
                df = df[df['status'].isin(filter_status)]
            if filter_customer:
                df = df[df['customer'].str.contains(filter_customer, na=False)]
            
            # 화면에 보여줄 컬럼 순서 정리
            display_cols = ["date", "customer", "name", "category", "stock", "status", "delivery_req_date", "note"]
            # 실제 데이터에 없는 컬럼이 있을 경우를 대비해 교집합만 선택
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.dataframe(df[final_cols], use_container_width=True)
            
            # 엑셀(CSV) 다운로드 버튼
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="💾 조회 내역 엑셀(CSV) 다운로드",
                data=csv,
                file_name='발주현황.csv',
                mime='text/csv',
            )
            st.caption("💡 팁: 위 표의 오른쪽 위에 있는 돋보기 아이콘으로 상세 검색이 가능하며, 다운로드한 파일은 엑셀에서 바로 열 수 있습니다.")
        else:
            st.info("조회된 데이터가 없습니다.")

elif menu == "현재고현황":
    st.header("📦 현재고 현황")

    # 새로고침 버튼
    if st.button("목록 새로고침"):
        st.rerun()

    # 데이터베이스에서 모든 데이터 가져오기
    docs = list(db.collection("inventory").order_by("date", direction=firestore.Query.DESCENDING).stream())

    if not docs:
        st.info("아직 등록된 데이터가 없습니다.")

    # 헤더
    col1, col2, col3, col4 = st.columns([3, 1, 2, 2])
    col1.write("**제품명 (구분)**")
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

else:
    st.header(f"🏗️ {menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
