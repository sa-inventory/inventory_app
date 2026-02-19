import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import json
import pandas as pd
import io
import uuid
# [NEW] 분리한 utils 파일에서 공통 함수 임포트
from utils import get_db, firestore
from ui_orders import render_order_entry, render_order_status, render_partner_order_status
from ui_production import render_weaving, render_dyeing, render_sewing
from ui_management import render_shipping_operations, render_shipping_status, render_inventory, render_product_master, render_partners, render_machines, render_codes, render_users, render_my_profile, render_company_settings
from ui_statistics import render_statistics
from ui_board import render_notice_board, render_schedule

# 1. 화면 기본 설정 (제목 등)
st.set_page_config(page_title="타올 생산 현황 관리", layout="wide")

# [수정] 상단 여백 축소 및 제목 스타일 변경
st.markdown("""
    <style>
        /* 메인 영역 상단 여백 줄이기 (기본값은 약 6rem) */
        .block-container {
            padding-top: 3rem !important;
        }
    </style>
""", unsafe_allow_html=True)

db = get_db()

# --- 로그인 기능 추가 ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["role"] = None

# [NEW] 자동 로그인 처리 (URL의 session_id 확인)
if not st.session_state["logged_in"]:
    session_id = st.query_params.get("session_id")
    if session_id:
        # DB에서 세션 정보 확인
        session_doc = db.collection("sessions").document(session_id).get()
        if session_doc.exists:
            s_data = session_doc.to_dict()
            user_id = s_data.get("user_id")
            
            # 사용자 정보 로드 및 로그인 상태 복원
            user_doc = db.collection("users").document(user_id).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                st.session_state["logged_in"] = True
                st.session_state["role"] = user_data.get("role", "user")
                st.session_state["user_name"] = user_data.get("name", user_id)
                st.session_state["user_id"] = user_id
                st.session_state["department"] = user_data.get("department", "")
                st.session_state["linked_partner"] = user_data.get("linked_partner", "")
                st.session_state["permissions"] = user_data.get("permissions", [])

# 로그인 화면 처리
if not st.session_state["logged_in"]:
    st.markdown("<h1 style='text-align: center;'>🔒 세안타올 생산 관리</h1>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        tab_staff, tab_partner = st.tabs(["직원 로그인", "거래처 로그인"])
        
        with tab_staff:
            with st.form("login_form"):
                st.subheader("직원 로그인")
                login_id = st.text_input("아이디", placeholder="아이디를 입력하세요")
                login_pw = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
                
                if st.form_submit_button("로그인", use_container_width=True):
                    user_doc = db.collection("users").document(login_id).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        if user_data.get("password") == login_pw:
                            # [NEW] 직원 로그인 탭에서 거래처 계정 로그인 차단
                            if user_data.get("role") == "partner":
                                st.error("거래처 계정입니다. '거래처 로그인' 탭을 이용해주세요.")
                            else:
                                st.session_state["logged_in"] = True
                                st.session_state["role"] = user_data.get("role", "user")
                                st.session_state["user_name"] = user_data.get("name", login_id)
                                st.session_state["user_id"] = login_id
                                st.session_state["department"] = user_data.get("department", "")
                                st.session_state["linked_partner"] = user_data.get("linked_partner", "")
                                # [NEW] 권한 목록 세션 저장
                                st.session_state["permissions"] = user_data.get("permissions") or []
                                if "current_menu" in st.session_state:
                                    del st.session_state["current_menu"]
                                
                                # [NEW] 세션 생성 및 URL 저장 (새로고침 유지용)
                                new_session_id = str(uuid.uuid4())
                                db.collection("sessions").document(new_session_id).set({
                                    "user_id": login_id,
                                    "created_at": datetime.datetime.now()
                                })
                                st.query_params["session_id"] = new_session_id
                                st.rerun()
                        else:
                            st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        st.error("등록되지 않은 아이디입니다.")

        with tab_partner:
            with st.form("partner_login_form"):
                st.subheader("거래처 로그인")
                # [수정] 보안을 위해 거래처 목록 선택 대신 아이디/비밀번호 입력 방식으로 변경
                p_id = st.text_input("아이디", placeholder="아이디를 입력하세요")
                p_pw = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
                
                if st.form_submit_button("로그인", use_container_width=True):
                    user_doc = db.collection("users").document(p_id).get()
                    if user_doc.exists:
                        user_data = user_doc.to_dict()
                        # 거래처 계정인지 확인
                        if user_data.get("role") == "partner":
                            if user_data.get("password") == p_pw:
                                st.session_state["logged_in"] = True
                                st.session_state["role"] = "partner"
                                st.session_state["user_name"] = user_data.get("name")
                                st.session_state["user_id"] = p_id
                                st.session_state["linked_partner"] = user_data.get("linked_partner")
                                if "current_menu" in st.session_state:
                                    del st.session_state["current_menu"]
                                
                                # [NEW] 세션 생성 및 URL 저장
                                new_session_id = str(uuid.uuid4())
                                db.collection("sessions").document(new_session_id).set({
                                    "user_id": p_id,
                                    "created_at": datetime.datetime.now()
                                })
                                st.query_params["session_id"] = new_session_id
                                st.rerun()
                            else:
                                st.error("비밀번호가 일치하지 않습니다.")
                        else:
                            st.error("거래처 계정이 아닙니다. 직원 로그인 탭을 이용해주세요.")
                    else:
                        st.error("등록되지 않은 아이디입니다.")
    st.stop()

# 3. [왼쪽 사이드바] 상품 등록 기능
with st.sidebar:
    # [NEW] 회사 정보 가져오기 (상호명 표시용)
    try:
        comp_info_ref = db.collection("settings").document("company_info").get()
        if comp_info_ref.exists:
            company_name = comp_info_ref.to_dict().get("name", "세안타올")
        else:
            company_name = "세안타올"
    except:
        company_name = "세안타올"
    # [수정] 회사명 글씨 크기 확대 및 스타일 개선
    st.markdown(f"""
        <div style='text-align: center; margin-bottom: 20px;'>
            <h1 style='margin:0; font-size: 2.2rem; font-weight: 700;'>🏢 {company_name}</h1>
            <h3 style='margin:0; font-size: 1.5rem; color: #333; font-weight: 600; margin-top: 5px;'>생산관리 시스템</h3>
        </div>
    """, unsafe_allow_html=True)
    user_display = st.session_state.get("user_name", st.session_state.get("role"))
    st.write(f"환영합니다.  **{user_display}**님!")
    
    st.divider()
    
    # 메뉴 선택 기능 추가
    if "current_menu" not in st.session_state:
        # 거래처 계정은 기본 메뉴가 '발주현황'
        if st.session_state.get("role") == "partner":
            st.session_state["current_menu"] = "발주현황(거래처)"
        else:
            st.session_state["current_menu"] = "공지사항"
    
    # [NEW] 하위 메뉴 상태 초기화
    if "current_sub_menu" not in st.session_state:
        st.session_state["current_sub_menu"] = None

    # [NEW] 권한 확인 헬퍼 함수
    def check_access(menu_name):
        # 관리자는 모든 메뉴 접근 가능
        if st.session_state.get("role") == "admin": return True
        # 사용자는 permissions 목록에 있는 메뉴만 접근 가능
        user_perms = st.session_state.get("permissions", [])
        return menu_name in user_perms

    # [NEW] 메뉴 아이템 생성 헬퍼 함수
    def menu_item(label, main_menu, sub_menu=None):
        # sub_menu가 없으면 label을 사용
        effective_sub_menu = sub_menu if sub_menu is not None else label
        
        # 현재 선택된 메뉴와 같으면 강조 스타일 적용
        is_selected = (st.session_state.get("current_menu") == main_menu and 
                       st.session_state.get("current_sub_menu") == effective_sub_menu)
        
        # 버튼 대신 st.markdown을 사용해 클릭 가능한 링크처럼 구현 (더 깔끔함)
        button_style = "background-color: #e6f3ff; color: #1c62b0; font-weight: bold;" if is_selected else "background-color: #f0f2f6;"
        
        if st.button(label, use_container_width=True, key=f"menu_{main_menu}_{effective_sub_menu}"):
            st.session_state["current_menu"] = main_menu
            st.session_state["current_sub_menu"] = effective_sub_menu
            
            # 공지사항 메뉴 클릭 시 특별 처리
            if main_menu == "공지사항":
                st.session_state["notice_view_mode"] = "list"
                st.session_state["selected_post_id"] = None
                st.session_state["notice_expander_state"] = False
                st.query_params.clear()
            st.rerun()

    # [NEW] 거래처(partner) 계정일 경우 메뉴 간소화
    if st.session_state.get("role") == "partner":
        st.info(f"**{st.session_state.get('linked_partner')}** 전용")
        menu_item("발주 현황 조회", "발주현황(거래처)")
            
    else:
        # [NEW] 직원용 전체 메뉴 구조
        cm = st.session_state.get("current_menu")
        
        # [NEW] 메뉴 버튼 스타일링 (위치 기반 지정)
        # [수정] CSS 방식 대신 이모지를 사용하여 직관적으로 구분 (더 안정적임)
        menu_item("📢 공지사항", "공지사항")
        menu_item("🗓️ 업무일정", "업무일정")
        
        st.divider()

        if check_access("발주서접수"):
            menu_item("📝 발주서접수", "발주서접수", "개별 접수")
            # [수정] 구분선이 잘 보이도록 색상(#ccc)을 진하게 하고 마진 조정
            st.markdown("<hr style='margin: 1rem 0; border: none; border-top: 1px solid #ccc;' />", unsafe_allow_html=True)

        if check_access("발주현황"):
            with st.expander("발주현황", expanded=(cm == "발주현황")):
                menu_item("발주현황 조회", "발주현황")
                if st.session_state.get("role") == "admin":
                    menu_item("발주내역삭제(엑셀업로드)", "발주현황")

        # [수정] 하위 메뉴 권한이 하나라도 있을 때만 상위 메뉴 표시
        has_production_access = check_access("제직현황") or check_access("염색현황") or check_access("봉제현황")
        if has_production_access:
            with st.expander("생산관리", expanded=(cm in ["제직현황", "염색현황", "봉제현황"])):
                if check_access("제직현황"):
                    with st.expander("제직현황", expanded=(cm == "제직현황")):
                        menu_item("제직대기 목록", "제직현황")
                        menu_item("제직중 목록", "제직현황")
                        menu_item("제직완료 목록", "제직현황")
                        menu_item("작업일지", "제직현황")
                        menu_item("생산일지", "제직현황")
                if check_access("염색현황"):
                    with st.expander("염색현황", expanded=(cm == "염색현황")):
                        menu_item("염색 대기 목록", "염색현황")
                        menu_item("염색중 목록", "염색현황")
                        menu_item("염색 완료 목록", "염색현황")
                        menu_item("색번 설정", "염색현황")
                if check_access("봉제현황"):
                    with st.expander("봉제현황", expanded=(cm == "봉제현황")):
                        menu_item("봉제 대기 목록", "봉제현황")
                        menu_item("봉제중 목록", "봉제현황")
                        menu_item("봉제 완료 목록", "봉제현황")

        # [수정] 하위 메뉴 권한이 하나라도 있을 때만 상위 메뉴 표시
        has_shipping_access = check_access("출고현황") or check_access("재고현황")
        if has_shipping_access:
            with st.expander("출고/재고", expanded=(cm in ["출고작업", "출고현황", "재고현황"])):
                if check_access("출고현황"):
                    with st.expander("출고작업", expanded=(cm == "출고작업")):
                        menu_item("주문별 출고", "출고작업")
                        menu_item("제품별 일괄 출고", "출고작업")
                    with st.expander("출고현황", expanded=(cm == "출고현황")):
                        menu_item("출고 완료 내역 (조회/명세서)", "출고현황")
                        menu_item("배송/운임 통계", "출고현황")
                if check_access("재고현황"):
                    with st.expander("재고현황", expanded=(cm == "재고현황")):
                        menu_item("재고 현황 조회", "재고현황")
                        menu_item("재고 임의 등록", "재고현황")

        if st.session_state.get("role") == "admin":
            with st.expander("내역조회", expanded=(cm == "내역조회")):
                menu_item("발주내역", "내역조회")
                menu_item("제직내역", "내역조회")
                menu_item("염색내역", "내역조회")
                menu_item("봉제내역", "내역조회")
                menu_item("출고/운임내역", "내역조회")

        # [수정] 하위 메뉴 권한이 하나라도 있을 때만 상위 메뉴 표시
        has_basic_info_access = check_access("제품 관리") or check_access("거래처관리") or check_access("제직기관리") or check_access("제품코드설정")
        if has_basic_info_access:
            with st.expander("기초정보관리", expanded=(cm in ["제품 관리", "거래처관리", "제직기관리", "제품코드설정"])):
                # [수정] 제품 관리 및 제품코드설정 통합
                if check_access("제품 관리") or check_access("제품코드설정"):
                    with st.expander("제품 관리", expanded=(cm == "제품 관리")):
                        if check_access("제품 관리"):
                            menu_item("제품 목록", "제품 관리")
                            menu_item("제품 등록", "제품 관리")
                        
                        if check_access("제품코드설정"):
                            csm = st.session_state.get("current_sub_menu")
                            with st.expander("제품코드설정", expanded=(csm in ["제품 종류", "사종", "중량", "사이즈"])):
                                menu_item("제품 종류", "제품 관리")
                                menu_item("사종", "제품 관리")
                                menu_item("중량", "제품 관리")
                                menu_item("사이즈", "제품 관리")

                if check_access("거래처관리"):
                    with st.expander("거래처관리", expanded=(cm == "거래처관리")):
                        menu_item("거래처 목록", "거래처관리")
                        menu_item("거래처 등록", "거래처관리")
                        menu_item("거래처 구분 관리", "거래처관리")
                if check_access("제직기관리"):
                    with st.expander("제직기관리", expanded=(cm == "제직기관리")):
                        menu_item("제직기 목록", "제직기관리")
                        menu_item("제직기 등록", "제직기관리")

        if st.session_state.get("role") == "admin":
            with st.expander("시스템관리", expanded=(cm in ["사용자 관리", "회사정보 관리"])):
                with st.expander("사용자 관리", expanded=(cm == "사용자 관리")):
                    menu_item("사용자 목록", "사용자 관리")
                    menu_item("사용자 등록", "사용자 관리")
                with st.expander("회사정보 관리", expanded=(cm == "회사정보 관리")):
                    menu_item("회사정보 조회", "회사정보 관리")
                    menu_item("정보 수정", "회사정보 관리")
    
    # [수정] 하단 여백 축소 (50px -> 10px)
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

    st.divider()
    
    menu_item("로그인 정보 설정", "로그인 정보 설정")
    
    if st.button("로그아웃", use_container_width=True):
        # [NEW] 로그아웃 시 세션 삭제 및 URL 초기화
        session_id = st.query_params.get("session_id")
        if session_id:
            db.collection("sessions").document(session_id).delete()
        st.query_params.clear()

        st.session_state["logged_in"] = False
        st.session_state["role"] = None
        if "user_name" in st.session_state:
            del st.session_state["user_name"]
        if "current_menu" in st.session_state:
            del st.session_state["current_menu"]
        
        # [수정] 로그아웃 시 달력 상태 초기화
        if "cal_year" in st.session_state: del st.session_state["cal_year"]
        if "cal_month" in st.session_state: del st.session_state["cal_month"]

        st.rerun()
 
menu = st.session_state["current_menu"]
sub_menu = st.session_state.get("current_sub_menu")

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "공지사항":
    render_notice_board(db)
elif menu == "업무일정":
    render_schedule(db)
elif menu == "발주서접수":
    render_order_entry(db, sub_menu)
elif menu == "발주현황":
    render_order_status(db, sub_menu)
elif menu == "발주현황(거래처)":
    render_partner_order_status(db)

elif menu == "제직현황":
    render_weaving(db, sub_menu)
elif menu == "염색현황":
    render_dyeing(db, sub_menu)
elif menu == "봉제현황":
    render_sewing(db, sub_menu)
elif menu == "출고작업":
    render_shipping_operations(db, sub_menu)
elif menu == "출고현황":
    render_shipping_status(db, sub_menu)
elif menu == "재고현황":
    render_inventory(db, sub_menu)
elif menu == "내역조회":
    render_statistics(db, sub_menu)
elif menu == "제품 관리":
    render_product_master(db, sub_menu)
elif menu == "거래처관리":
    render_partners(db, sub_menu)
elif menu == "제직기관리":
    render_machines(db, sub_menu)
elif menu == "사용자 관리":
    render_users(db, sub_menu)
elif menu == "회사정보 관리":
    render_company_settings(db)
elif menu == "로그인 정보 설정":
    render_my_profile(db)
else:
    st.header(f"{menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
