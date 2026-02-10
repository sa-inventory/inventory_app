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
from ui_orders import render_order_entry, render_order_status
from ui_production import render_weaving, render_dyeing, render_sewing
from ui_management import render_shipping, render_inventory, render_product_master, render_partners, render_machines, render_codes, render_users

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
    st.session_state["logged_in"] = True   # 개발 편의를 위해 True로 설정
    st.session_state["role"] = "admin"     # 개발 편의를 위해 admin으로 설정

# 개발 중 로그인 비활성화 (나중에 주석 해제하여 다시 사용)
# if not st.session_state["logged_in"]:
#     st.subheader("로그인")
#     login_id = st.text_input("아이디", placeholder="admin 또는 guest")
#     login_pw = st.text_input("비밀번호", type="password", placeholder="1234")
#     
#     if st.button("로그인"):
#         # 예시를 위해 하드코딩된 계정 사용 (실제로는 DB에서 확인 권장)
#         if login_id == "admin" and login_pw == "1234":
#             st.session_state["logged_in"] = True
#             st.session_state["role"] = "admin"
#             st.rerun()
#         elif login_id == "guest" and login_pw == "1234":
#             st.session_state["logged_in"] = True
#             st.session_state["role"] = "guest"
#             st.rerun()
#         else:
#             st.error("아이디 또는 비밀번호를 확인하세요.")
#     st.stop()  # 로그인 전에는 아래 내용을 보여주지 않음

# 3. [왼쪽 사이드바] 상품 등록 기능
with st.sidebar:
    st.markdown("<h2 style='text-align: center; margin-bottom: 20px;'>🏭 세안타올<br>생산관리 현황</h2>", unsafe_allow_html=True)
    st.write(f"환영합니다, **{st.session_state['role']}**님!")
    # if st.button("로그아웃"):
    #     st.session_state["logged_in"] = False
    #     st.session_state["role"] = None
    #     st.rerun()
    st.divider()
    
    # 메뉴 선택 기능 추가
    if "current_menu" not in st.session_state:
        st.session_state["current_menu"] = "발주서접수"

    st.subheader("메뉴 선택")
    with st.expander("🏭 생산관리", expanded=True):
        if st.button("📑 발주서접수", use_container_width=True):
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
        if st.session_state.get("role") == "admin":
            if st.button("👤 사용자 관리", use_container_width=True):
                st.session_state["current_menu"] = "사용자 관리"
                st.rerun()
            
    menu = st.session_state["current_menu"]

# 4. [메인 화면] 메뉴별 기능 구현
if menu == "발주서접수":
    render_order_entry(db)
elif menu == "발주현황":
    render_order_status(db)

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
else:
    st.header(f"🏗️ {menu}")
    st.info(f"'{menu}' 기능은 추후 업데이트될 예정입니다.")
