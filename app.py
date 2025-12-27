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
    st.subheader("메뉴 선택")
    main_category = st.radio("카테고리", ["생산관리", "기초정보관리"])
    
    if main_category == "생산관리":
        menu = st.radio("업무 메뉴", 
            ["발주서접수", "제직현황", "염색현황", "봉제현황", "출고현황", "현재고현황"])
    else:
        menu = st.radio("관리 메뉴", ["거래처관리", "기초코드관리"])

# --- 공통 함수: 기초 코드 가져오기 ---
def get_common_codes(code_type, default_values):
    doc_ref = db.collection("settings").document("codes")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        return data.get(code_type, default_values)
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

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "발주서접수":
    st.header("📑 발주서 접수")
    
    # 탭을 사용하여 '등록'과 '조회' 화면 분리
    tab1, tab2 = st.tabs(["📝 신규 발주 등록", "🔍 발주 현황 조회 및 관리"])
    
    with tab1:
        if st.session_state["role"] == "admin":
            # 기초 데이터 불러오기
            towel_types = get_common_codes("towel_types", ["세면타올", "바스타올", "핸드타올", "비치타올", "기타"])
            weaving_types = get_common_codes("weaving_types", ["30수 연사", "40수 코마사", "무지", "자카드", "기타"])
            customer_list = get_partners("발주처")

            with st.form("order_form"):
                st.subheader("기본 발주 정보")
                c1, c2, c3 = st.columns(3)
                order_date = c1.date_input("발주접수일", datetime.date.today())
                # 거래처 목록이 없으면 텍스트 입력, 있으면 선택박스
                if customer_list:
                    customer = c2.selectbox("발주처 선택", customer_list)
                else:
                    customer = c2.text_input("발주처 (기초정보관리에서 거래처를 등록하세요)")
                delivery_req_date = c3.date_input("납품요청일", datetime.date.today() + datetime.timedelta(days=7))

                st.subheader("제품 상세 정보")
                c1, c2, c3, c4 = st.columns(4)
                name = c1.text_input("제품명 (타올 종류)")
                category = c2.selectbox("구분", towel_types)
                weaving_type = c3.selectbox("제직타입", weaving_types)
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

        with st.form("search_form"):
            c1, c2, c3 = st.columns(3)
            # 날짜 범위 선택 (기본값: 최근 30일)
            today = datetime.date.today()
            date_range = c1.date_input("조회 기간", [today - datetime.timedelta(days=30), today])
            filter_status = c2.multiselect("진행 상태", ["발주접수", "제직", "염색", "봉제", "출고"], default=["발주접수", "제직", "염색", "봉제"])
            filter_customer = c3.text_input("발주처 검색")
            
            search_btn = st.form_submit_button("🔍 조회하기")

        if search_btn:
            # 날짜 필터링을 위해 datetime 변환
            start_date = datetime.datetime.combine(date_range[0], datetime.time.min)
            end_date = datetime.datetime.combine(date_range[1], datetime.time.max) if len(date_range) > 1 else datetime.datetime.combine(date_range[0], datetime.time.max)

            docs = db.collection("inventory").where("date", ">=", start_date).where("date", "<=", end_date).order_by("date", direction=firestore.Query.DESCENDING).stream()

        # 데이터를 리스트로 변환
            rows = []
            for doc in docs:
                d = doc.to_dict()
                d['id'] = doc.id
                if 'date' in d and d['date']:
                    d['date'] = d['date'].strftime("%Y-%m-%d")
                rows.append(d)
                
            if rows:
                df = pd.DataFrame(rows)
                
                # 상태 및 거래처 필터 (메모리 상에서 2차 필터)
                if filter_status:
                    df = df[df['status'].isin(filter_status)]
                if filter_customer:
                    df = df[df['customer'].str.contains(filter_customer, na=False)]
                
                display_cols = ["date", "customer", "name", "category", "stock", "status", "delivery_req_date", "note"]
                final_cols = [c for c in display_cols if c in df.columns]
                
                st.dataframe(df[final_cols], use_container_width=True)
                
                csv = df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="💾 엑셀 다운로드",
                    data=csv,
                    file_name='발주현황.csv',
                    mime='text/csv',
                )
            else:
                st.info("해당 기간에 조회된 데이터가 없습니다.")
        else:
            st.info("조회 기간을 선택하고 조회 버튼을 눌러주세요.")

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

elif menu == "거래처관리":
    st.header("🏢 거래처 관리")
    
    tab1, tab2 = st.tabs(["➕ 거래처 등록", "📋 거래처 목록"])
    
    # 기초 코드에서 거래처 구분 가져오기
    partner_types = get_common_codes("partner_types", ["발주처", "염색업체", "봉제업체", "배송업체", "기타"])

    with tab1:
        with st.form("partner_form"):
            c1, c2 = st.columns(2)
            p_type = c1.selectbox("거래처 구분", partner_types)
            p_name = c2.text_input("거래처명", placeholder="상호명 입력")
            
            c1, c2, c3 = st.columns(3)
            p_rep = c1.text_input("대표자명")
            p_biz_num = c2.text_input("사업자번호")
            p_item = c3.text_input("업태/종목")
            
            c1, c2, c3 = st.columns(3)
            p_phone = c1.text_input("전화번호")
            p_fax = c2.text_input("팩스번호")
            p_email = c3.text_input("이메일")
            
            p_address = st.text_input("주소")
            p_account = st.text_input("계좌번호")
            p_note = st.text_area("기타사항")
            
            if st.form_submit_button("거래처 저장"):
                if p_name:
                    db.collection("partners").add({
                        "type": p_type,
                        "name": p_name,
                        "rep_name": p_rep,
                        "biz_num": p_biz_num,
                        "item": p_item,
                        "phone": p_phone,
                        "fax": p_fax,
                        "email": p_email,
                        "address": p_address,
                        "account": p_account,
                        "note": p_note,
                        "reg_date": datetime.datetime.now()
                    })
                    st.success(f"{p_name} 저장 완료!")
                    st.rerun()
                else:
                    st.error("거래처명을 입력해주세요.")

    with tab2:
        # 거래처 목록 조회
        partners = list(db.collection("partners").order_by("name").stream())
        if partners:
            data = []
            for p in partners:
                pd = p.to_dict()
                pd['id'] = p.id
                data.append(pd)
            df = pd.DataFrame(data)
            
            # 보여줄 컬럼 선택
            cols = ["type", "name", "rep_name", "phone", "address", "note"]
            st.dataframe(df[cols], use_container_width=True)
            
            # 삭제 기능 (간단히 구현)
            st.caption("거래처 삭제는 관리자에게 문의하세요. (추후 구현 예정)")
        else:
            st.info("등록된 거래처가 없습니다.")

elif menu == "기초코드관리":
    st.header("⚙️ 기초 코드 관리")
    st.info("콤보박스에 표시될 항목들을 관리합니다.")
    
    code_tabs = st.tabs(["타올 구분", "제직 타입", "거래처 구분"])
    
    # 코드 관리용 함수
    def manage_code(code_key, default_list, label):
        current_list = get_common_codes(code_key, default_list)
        st.write(f"현재 등록된 {label}: {', '.join(current_list)}")
        
        new_val = st.text_input(f"추가할 {label}", key=f"new_{code_key}")
        if st.button(f"추가", key=f"btn_add_{code_key}"):
            if new_val and new_val not in current_list:
                current_list.append(new_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("추가되었습니다.")
                st.rerun()
        
        del_val = st.selectbox(f"삭제할 {label} 선택", ["선택하세요"] + current_list, key=f"del_{code_key}")
        if st.button(f"삭제", key=f"btn_del_{code_key}"):
            if del_val != "선택하세요":
                current_list.remove(del_val)
                db.collection("settings").document("codes").set({code_key: current_list}, merge=True)
                st.success("삭제되었습니다.")
                st.rerun()

    with code_tabs[0]: manage_code("towel_types", ["세면타올", "바스타올", "핸드타올", "비치타올", "기타"], "타올 구분")
    with code_tabs[1]: manage_code("weaving_types", ["30수 연사", "40수 코마사", "무지", "자카드", "기타"], "제직 타입")
    with code_tabs[2]: manage_code("partner_types", ["발주처", "염색업체", "봉제업체", "배송업체", "기타"], "거래처 구분")

else:
    st.header(f"🏗️ {menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
