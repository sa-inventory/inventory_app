import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import json
import pandas as pd
import io
# [NEW] 분리한 utils 파일에서 공통 함수 임포트
from utils import get_db, firestore
from ui_orders import render_order_entry, render_order_status, render_partner_order_status
from ui_production import render_weaving, render_dyeing, render_sewing
from ui_management import render_shipping, render_inventory, render_product_master, render_partners, render_machines, render_codes, render_users, render_my_profile, render_company_settings
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
                            st.session_state["logged_in"] = True
                            st.session_state["role"] = user_data.get("role", "user")
                            st.session_state["user_name"] = user_data.get("name", login_id)
                            st.session_state["user_id"] = login_id
                            st.session_state["department"] = user_data.get("department", "")
                            st.session_state["linked_partner"] = user_data.get("linked_partner", "")
                            if "current_menu" in st.session_state:
                                del st.session_state["current_menu"]
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
    st.markdown("<h2 style='text-align: center; margin-bottom: 20px;'>🏭 세안타올<br>생산관리 시스템</h2>", unsafe_allow_html=True)
    user_display = st.session_state.get("user_name", st.session_state.get("role"))
    st.write(f"환영합니다, **{user_display}**님!")
    
    if st.button("로그아웃", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["role"] = None
        if "user_name" in st.session_state:
            del st.session_state["user_name"]
        if "current_menu" in st.session_state:
            del st.session_state["current_menu"]
        st.rerun()
    
    if st.button("⚙️ 로그인 정보 설정", use_container_width=True):
        st.session_state["current_menu"] = "로그인 정보 설정"
        st.rerun()
        
    st.divider()
    
    # 메뉴 선택 기능 추가
    if "current_menu" not in st.session_state:
        # 거래처 계정은 기본 메뉴가 '발주현황'
        if st.session_state.get("role") == "partner":
            st.session_state["current_menu"] = "발주현황(거래처)"
        else:
            st.session_state["current_menu"] = "공지사항"

    # [NEW] 거래처(partner) 계정일 경우 메뉴 간소화
    if st.session_state.get("role") == "partner":
        st.info(f"🏢 **{st.session_state.get('linked_partner')}** 전용")
        if st.button("📊 발주 현황 조회", use_container_width=True):
            st.session_state["current_menu"] = "발주현황(거래처)"
            st.rerun()
            
    else:
        # [기존] 내부 직원용 메뉴
        # [NEW] 공지사항 버튼 독립 배치
        if st.button("📢 공지사항", use_container_width=True):
            st.session_state["current_menu"] = "공지사항"
            st.rerun()
        if st.button("📅 업무일정", use_container_width=True):
            st.session_state["current_menu"] = "업무일정"
            st.rerun()

        st.subheader("메뉴 선택")
        with st.expander("🏭 생산관리", expanded=True):
            if st.button(" 발주서접수", use_container_width=True):
                st.session_state["current_menu"] = "발주서접수"
                st.rerun()
            if st.button("📊 발주현황", use_container_width=True):
                st.session_state["current_menu"] = "발주현황"
                st.rerun()
            if st.button("🧵 제직현황", use_container_width=True):
                st.session_state["current_menu"] = "제직현황"
                st.rerun()
            if st.button("🎨 염색현황", use_container_width=True):
                st.session_state["current_menu"] = "염색현황"
                st.rerun()
            if st.button("🪡 봉제현황", use_container_width=True):
                st.session_state["current_menu"] = "봉제현황"
                st.rerun()
            if st.button("🚚 출고현황", use_container_width=True):
                st.session_state["current_menu"] = "출고현황"
                st.rerun()
            if st.button("📦 재고현황", use_container_width=True):
                st.session_state["current_menu"] = "재고현황"
                st.rerun()
            if st.button("📈 공정별통계", use_container_width=True):
                st.session_state["current_menu"] = "통합통계"
                st.rerun()

        with st.expander("⚙️ 기초정보관리", expanded=True):
            if st.button("📦 제품 관리", use_container_width=True):
                st.session_state["current_menu"] = "제품 관리"
                st.rerun()
            if st.button("🏢 거래처관리", use_container_width=True):
                st.session_state["current_menu"] = "거래처관리"
                st.rerun()
            if st.button("🏭 제직기관리", use_container_width=True):
                st.session_state["current_menu"] = "제직기관리"
                st.rerun()
            if st.button("📝 제품코드설정", use_container_width=True):
                st.session_state["current_menu"] = "제품코드설정"
                st.rerun()
            if st.button("🏢 자사 정보 설정", use_container_width=True):
                st.session_state["current_menu"] = "자사 정보 설정"
                st.rerun()
            if st.session_state.get("role") == "admin":
                if st.button("👤 사용자 관리", use_container_width=True):
                    st.session_state["current_menu"] = "사용자 관리"
                    st.rerun()
            
    menu = st.session_state["current_menu"]

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "공지사항":
    render_notice_board(db)
elif menu == "업무일정":
    render_schedule(db)
elif menu == "발주서접수":
    render_order_entry(db)
elif menu == "발주현황":
    render_order_status(db)
elif menu == "발주현황(거래처)":
    render_partner_order_status(db)

elif menu == "제직현황":
    render_weaving(db)
elif menu == "염색현황":
    render_dyeing(db)
elif menu == "봉제현황":
    render_sewing(db)
elif menu == "출고현황":
    render_shipping(db)
elif menu == "재고현황":
    render_inventory(db)
elif menu == "통합통계":
    render_statistics(db)
elif menu == "제품 관리":
    render_product_master(db)
elif menu == "거래처관리":
    render_partners(db)
elif menu == "제직기관리":
    render_machines(db)
elif menu == "제품코드설정":
    render_codes(db)
elif menu == "사용자 관리":
    render_users(db)
elif menu == "자사 정보 설정":
    render_company_settings(db)
elif menu == "로그인 정보 설정":
    render_my_profile(db)
else:
    st.header(f"🏗️ {menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
