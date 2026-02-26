import streamlit as st
import pandas as pd
import datetime
import io
from firebase_admin import firestore
from utils import get_partners, generate_report_html, get_common_codes, manage_code_with_code

def render_dyeing(db, sub_menu):
    st.header("염색 현황")
    st.info("제직이 완료된 건을 염색 공장에서 작업하고 봉제 단계로 넘깁니다.")

    # 염색 업체 목록 가져오기
    dyeing_partners = get_partners("염색업체")

    # [NEW] 색번 기초 코드 가져오기
    color_codes = get_common_codes("color_codes", [])
    # [수정] 색번(색상) 형식으로 표시 (예: W0041 (신백색)) - 순서 재확인
    color_opts = ["선택하세요"] + [f"{c['code']} ({c['name']})" for c in color_codes] if color_codes else ["선택하세요"]

    # --- 1. 염색 대기 탭 ---
    if sub_menu == "염색 대기 목록":
        st.subheader("염색 대기 목록 (제직완료)")
        
        # [NEW] 목록 갱신을 위한 키 초기화 (염색대기)
        if "key_dyeing_wait" not in st.session_state:
            st.session_state["key_dyeing_wait"] = 0
            
        docs = db.collection("orders").where("status", "==", "제직완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        
        # 날짜순 정렬
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))

        if rows:
            df = pd.DataFrame(rows)
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            col_map = {
                "order_no": "발주번호", "customer": "발주처", "name": "제품명", 
                "color": "색상", "stock": "수량", "weight": "중량(g)", 
                "prod_weight_kg": "제직중량(kg)", "roll_no": "롤번호", "date": "접수일"
            }
            display_cols = ["order_no", "roll_no", "customer", "name", "color", "stock", "weight", "prod_weight_kg", "date"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 염색 출고할 항목을 선택하세요. (다중 선택 가능)")
            # [수정] 다중 선택 모드로 변경
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="multi-row", key=f"df_dye_wait_{st.session_state['key_dyeing_wait']}")
            
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]

                # [NEW] 다중 선택 시: 염색 작업 지시서 출력 (현장용)
                with st.expander("염색 작업 지시서 출력 (현장 확인용)", expanded=False):
                    st.info("선택한 항목에 대해 **염색업체**와 **솥번호**를 지정하여 작업 지시서를 출력합니다. (이 정보는 DB에 저장되지 않습니다)")
                    
                    # 데이터 에디터용 데이터프레임 생성
                    edit_df = selected_rows.copy()
                    # 기본값 설정
                    edit_df['염색업체'] = "" 
                    edit_df['솥번호'] = "1"
                    edit_df['비고'] = ""
                    
                    # 표시할 컬럼 정리
                    edit_view = edit_df[['name', 'color', 'prod_weight_kg', 'stock', '염색업체', '솥번호', '비고']].rename(columns={
                        'name': '제품명', 'color': '색상', 'prod_weight_kg': '중량(kg)', 'stock': '수량'
                    })
                    
                    # 데이터 에디터 (업체, 솥번호 입력)
                    edited_data = st.data_editor(
                        edit_view,
                        column_config={
                            "제품명": st.column_config.TextColumn(disabled=True),
                            "색상": st.column_config.TextColumn(disabled=True),
                            "중량(kg)": st.column_config.NumberColumn(disabled=True, format="%.1f"),
                            "수량": st.column_config.NumberColumn(disabled=True),
                            "염색업체": st.column_config.SelectboxColumn("염색업체", options=dyeing_partners, required=True),
                            "솥번호": st.column_config.TextColumn("솥번호", help="같은 업체 내에서 솥번호별로 그룹화됩니다."),
                            "비고": st.column_config.TextColumn("비고")
                        },
                        hide_index=True,
                        use_container_width=True,
                        key="dye_print_editor"
                    )
                    
                    # [NEW] 인쇄 옵션 설정
                    with st.expander("🖨️ 인쇄 옵션 설정"):
                        po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                        p_title = po_c1.text_input("제목", value="염색 작업 지시서", key="dye_p_title")
                        p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="dye_p_ts")
                        p_body_size = po_c3.number_input("본문 글자 크기(px)", value=12, step=1, key="dye_p_bs")
                        p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="dye_p_pad")
                        
                        st.caption("페이지 여백 (mm)")
                        po_c5, po_c6, po_c7, po_c8 = st.columns(4)
                        p_m_top = po_c5.number_input("상단", value=15, step=1, key="dye_p_mt")
                        p_m_bottom = po_c6.number_input("하단", value=15, step=1, key="dye_p_mb")
                        p_m_left = po_c7.number_input("좌측", value=15, step=1, key="dye_p_ml")
                        p_m_right = po_c8.number_input("우측", value=15, step=1, key="dye_p_mr")
                        
                        po_c9, po_c10 = st.columns(2)
                        dye_p_bo = po_c9.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="dye_p_bo")
                        dye_p_bi = po_c10.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="dye_p_bi")

                    if st.button("🖨️ 작업 지시서 인쇄"):
                        # 그룹화 및 HTML 생성 로직
                        print_html = f"""
                        <html>
                        <head>
                            <title>{p_title}</title>
                            <style>
                                @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                                h2 {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 10px; font-size: {p_title_size}px; margin-top: 0; }}
                                .partner-section {{ margin-bottom: 30px; border: 1px solid #999; padding: 15px; page-break-inside: avoid; }}
                                .partner-title {{ font-size: {p_body_size + 6}px; font-weight: bold; background-color: #eee; padding: 5px; margin-bottom: 10px; }}
                                .pot-section {{ margin-left: 10px; margin-bottom: 15px; }}
                                .pot-title {{ font-size: {p_body_size + 4}px; font-weight: bold; color: #0066cc; margin-bottom: 5px; border-bottom: 1px solid #ddd; }}
                                table {{ width: 100%; border-collapse: collapse; font-size: {p_body_size}px; margin-bottom: 5px; border: {dye_p_bo}px solid #ccc; }}
                                th, td {{ border: {dye_p_bi}px solid #ccc; padding: {p_padding}px; text-align: center; }}
                                th {{ background-color: #f8f9fa; }}
                                .total-row {{ font-weight: bold; background-color: #fffbe6; }}
                                @media screen {{ body {{ display: none; }} }}
                            </style>
                        </head>
                        <body onload="window.print()">
                            <h2>{p_title}</h2>
                            <div style="text-align: right; font-size: 10px; margin-bottom: 10px;">출력일시: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
                        """
                        
                        # 그룹화: 염색업체 -> 솥번호
                        if not edited_data.empty:
                            # 업체가 없는 경우 '미지정' 처리
                            edited_data['염색업체'] = edited_data['염색업체'].fillna('미지정').replace('', '미지정')
                            
                            for partner, p_group in edited_data.groupby('염색업체'):
                                print_html += f"<div class='partner-section'><div class='partner-title'>🏭 업체: {partner}</div>"
                                
                                for pot, pot_group in p_group.groupby('솥번호'):
                                    # 솥 합계 계산
                                    sum_weight = pot_group['중량(kg)'].sum()
                                    sum_qty = pot_group['수량'].sum()
                                    
                                    print_html += f"<div class='pot-section'><div class='pot-title'>🔹 솥번호: {pot}</div>"
                                    print_html += pot_group.to_html(index=False, classes='table', border=0)
                                    print_html += f"<div style='text-align:right; font-weight:bold; margin-top:5px;'>[합계] 수량: {sum_qty:,}장 / 중량: {sum_weight:,.1f}kg</div></div>"
                                
                                print_html += "</div>"
                        
                        print_html += "</body></html>"
                        st.components.v1.html(print_html, height=0, width=0)

                # [기존] 개별 출고 처리 (단일 선택 시에만 표시)
                if len(selected_indices) == 1:
                    idx = selected_indices[0]
                    sel_row = df.iloc[idx]
                    sel_id = sel_row['id']
                
                    st.divider()
                    st.markdown(f"### 염색 출고 정보 입력: **{sel_row['name']}**")
                    
                    with st.form("dyeing_start_form"):
                        c1, c2 = st.columns(2)
                        d_date = c1.date_input("염색출고일", datetime.date.today())
                        d_partner = c2.selectbox("염색업체", dyeing_partners if dyeing_partners else ["직접입력"])
                        
                        c3, c4 = st.columns(2)
                        # [NEW] 색번 선택 콤보박스 추가
                        d_color_code_sel = c3.selectbox("색번 선택", color_opts)
                        
                        # 기본값으로 제직 생산 중량 사용
                        def_weight = float(sel_row.get('prod_weight_kg', 0))
                        d_weight = c4.number_input("출고중량(kg)", value=def_weight, step=0.1, format="%.1f")
                        
                        d_note = st.text_input("염색사항(비고)")
                        
                        if st.form_submit_button("염색 출고 (작업시작)"):
                            # 색번 파싱
                            sel_cc, sel_cn = "", ""
                            if d_color_code_sel != "선택하세요":
                                try:
                                    sel_cc, rest = d_color_code_sel.split(" (", 1)
                                    sel_cn = rest[:-1]
                                except:
                                    sel_cc = d_color_code_sel

                            db.collection("orders").document(sel_id).update({
                                "status": "염색중",
                                "dyeing_out_date": str(d_date),
                                "dyeing_partner": d_partner,
                                "dyeing_out_weight": d_weight,
                                "dyeing_note": d_note,
                                "dyeing_color_code": sel_cc,
                                "dyeing_color_name": sel_cn
                            })
                            st.success("염색중 상태로 변경되었습니다.")
                            st.session_state["key_dyeing_wait"] += 1 # 목록 선택 초기화
                            st.rerun()
        else:
            st.info("염색 대기 중인 건이 없습니다.")

    # --- 2. 염색중 탭 ---
    elif sub_menu == "염색중 목록":
        st.subheader("염색중 목록")
        
        if "key_dyeing_ing" not in st.session_state:
            st.session_state["key_dyeing_ing"] = 0
            
        docs = db.collection("orders").where("status", "==", "염색중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            # 비고 컬럼이 없는 경우 빈 값으로 초기화 (데이터가 없을 때 오류 방지)
            if 'dyeing_note' not in df.columns:
                df['dyeing_note'] = ""

            col_map = {
                "order_no": "발주번호", "dyeing_partner": "염색업체", "dyeing_out_date": "출고일",
                "name": "제품명", "color": "색상", "dyeing_color_code": "색번", "stock": "수량", "dyeing_out_weight": "출고중량(kg)",
                "roll_no": "롤번호", "dyeing_note": "비고"
            }
            display_cols = ["dyeing_out_date", "dyeing_partner", "order_no", "roll_no", "name", "color", "dyeing_color_code", "stock", "dyeing_out_weight", "dyeing_note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 관리할 항목을 선택하세요.")
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="single-row", key=f"df_dye_ing_{st.session_state['key_dyeing_ing']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 작업 관리: **{sel_row['name']}**")
                
                tab_act1, tab_act2 = st.tabs(["염색 완료 처리", "정보 수정 / 취소"])
                
                with tab_act1:
                    st.write("염색 완료(입고) 정보를 입력하세요.")
                    c1, c2 = st.columns(2)
                    d_in_date = c1.date_input("염색완료일(입고일)", datetime.date.today())
                    d_stock = c2.number_input("입고수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                    
                    c3, c4 = st.columns(2)
                    # 기본값으로 출고 중량 사용
                    def_weight = float(sel_row.get('dyeing_out_weight', 0)) if not pd.isna(sel_row.get('dyeing_out_weight')) else 0.0
                    d_weight = c3.number_input("입고중량(kg)", value=def_weight, step=0.1, format="%.1f")
                    d_price = c4.number_input("염색단가(원)", min_value=0, step=1)
                    
                    d_vat_inc = st.checkbox("부가세 포함", value=False, key="dye_vat_check")
                    
                    base_calc = int(d_weight * d_price)
                    if d_vat_inc:
                        d_supply = int(base_calc / 1.1)
                        d_vat = base_calc - d_supply
                        d_total = base_calc
                    else:
                        d_supply = base_calc
                        d_vat = int(base_calc * 0.1)
                        d_total = base_calc + d_vat
                    
                    st.info(f"💰 **염색비용 합계**: {d_total:,}원 (공급가: {d_supply:,}원 / 부가세: {d_vat:,}원)")
                    
                    if st.button("염색 완료 (봉제대기로 이동)"):
                        db.collection("orders").document(sel_id).update({
                            "status": "염색완료",
                            "dyeing_in_date": str(d_in_date),
                            "stock": d_stock,
                            "dyeing_in_weight": d_weight,
                            "dyeing_unit_price": d_price,
                            "dyeing_amount": d_total,
                            "dyeing_supply": d_supply,
                            "dyeing_vat": d_vat,
                            "vat_included": d_vat_inc
                        })
                        st.success(f"염색이 완료되었습니다. (합계: {d_total:,}원)")
                        st.session_state["key_dyeing_ing"] += 1
                        st.rerun()
                            
                with tab_act2:
                    with st.form("dyeing_edit_form"):
                        st.write("출고 정보를 수정합니다.")
                        st.caption("💡 색번 목록이 보이지 않으면 **[🎨 색번 설정]** 탭에서 먼저 등록하세요.")
                        c1, c2 = st.columns(2)
                        e_date = c1.date_input("염색출고일", datetime.datetime.strptime(sel_row['dyeing_out_date'], "%Y-%m-%d").date() if sel_row.get('dyeing_out_date') else datetime.date.today())
                        e_partner = c2.selectbox("염색업체", dyeing_partners if dyeing_partners else ["직접입력"], index=dyeing_partners.index(sel_row['dyeing_partner']) if sel_row.get('dyeing_partner') in dyeing_partners else 0)
                        
                        c3, c4 = st.columns(2)
                        # [NEW] 색번 수정
                        curr_cc = sel_row.get('dyeing_color_code', '')
                        curr_cn = sel_row.get('dyeing_color_name', '')
                        # [수정] 색번(색상) 형식 유지
                        curr_val = f"{curr_cc} ({curr_cn})" if curr_cc and curr_cn else "선택하세요"
                        # 옵션에 없으면 추가 (기존 데이터 보존)
                        if curr_val not in color_opts and curr_val != "선택하세요":
                             color_opts.append(curr_val)
                        
                        e_color_sel = c3.selectbox("색번", color_opts, index=color_opts.index(curr_val) if curr_val in color_opts else 0)
                        e_weight = c4.number_input("출고중량(kg)", value=float(sel_row.get('dyeing_out_weight', 0)), step=0.1, format="%.1f")
                        
                        e_note = st.text_input("염색사항", value=sel_row.get('dyeing_note', ''))
                        
                        if st.form_submit_button("수정 저장"):
                            e_cc, e_cn = "", ""
                            if e_color_sel != "선택하세요":
                                try: e_cc, rest = e_color_sel.split(" (", 1); e_cn = rest[:-1]
                                except: e_cc = e_color_sel

                            db.collection("orders").document(sel_id).update({
                                "dyeing_out_date": str(e_date),
                                "dyeing_partner": e_partner,
                                "dyeing_out_weight": e_weight,
                                "dyeing_note": e_note,
                                "dyeing_color_code": e_cc,
                                "dyeing_color_name": e_cn
                            })
                            st.success("수정되었습니다.")
                            st.session_state["key_dyeing_ing"] += 1
                            st.rerun()
                    
                    st.markdown("#### 작업 취소")
                    if st.button("염색 취소 (대기로 되돌리기)", type="primary"):
                        db.collection("orders").document(sel_id).update({
                            "status": "제직완료"
                        })
                        st.success("취소되었습니다.")
                        st.session_state["key_dyeing_ing"] += 1
                        st.rerun()
        else:
            st.info("현재 염색 중인 작업이 없습니다.")

    # --- 3. 염색 완료 탭 ---
    elif sub_menu == "염색 완료 목록":
        st.subheader("염색 완료 목록")
        
        if "key_dyeing_done" not in st.session_state:
            st.session_state["key_dyeing_done"] = 0
        
        # 검색 조건 (기간 + 염색업체 + 발주처)
        with st.expander("검색", expanded=True):
            with st.form("search_dye_done"):
                c1, c2, c3 = st.columns([2, 1, 1])
                today = datetime.date.today()
                s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
                s_partner = c2.text_input("염색업체")
                s_customer = c3.text_input("발주처")
                st.form_submit_button("조회")

        # 날짜 범위 계산
        if len(s_date) == 2:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[1], datetime.time.max)
        else:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[0], datetime.time.max)

        # [수정] 다음 공정으로 넘어간 내역도 조회되도록 상태 조건 확대
        target_statuses = ["염색완료", "봉제중", "봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 1. 날짜 필터 (dyeing_in_date 기준)
            d_date_str = d.get('dyeing_in_date')
            if d_date_str:
                try:
                    d_date_obj = datetime.datetime.strptime(d_date_str, "%Y-%m-%d")
                    if not (start_dt <= d_date_obj <= end_dt): continue
                except:
                    continue
            else:
                continue
            
            # 2. 염색업체 필터
            if s_partner and s_partner not in d.get('dyeing_partner', ''):
                continue

            # 3. 발주처 필터
            if s_customer and s_customer not in d.get('customer', ''):
                continue
                
            rows.append(d)
            
        # 최신순 정렬 (완료일 기준)
        rows.sort(key=lambda x: x.get('dyeing_in_date', ''), reverse=True)

        if rows:
            df = pd.DataFrame(rows)
            
            # 합계 계산
            total_stock = df['stock'].sum() if 'stock' in df.columns else 0
            total_weight = df['dyeing_in_weight'].sum() if 'dyeing_in_weight' in df.columns else 0.0
            total_amount = df['dyeing_amount'].sum() if 'dyeing_amount' in df.columns else 0
            
            st.markdown(f"### 📊 합계: 수량 **{total_stock:,}장** / 중량 **{total_weight:,.1f}kg** / 금액 **{total_amount:,}원**")
            
            col_map = {
                "order_no": "발주번호", "dyeing_partner": "염색업체", "dyeing_in_date": "완료일",
                "name": "제품명", "color": "색상", "dyeing_color_code": "색번", "stock": "수량", "roll_no": "롤번호",
                "dyeing_in_weight": "입고중량(kg)", "dyeing_unit_price": "단가", "dyeing_amount": "금액",
                "customer": "발주처"
            }
            display_cols = ["dyeing_in_date", "dyeing_partner", "customer", "order_no", "roll_no", "name", "color", "dyeing_color_code", "stock", "dyeing_in_weight", "dyeing_unit_price", "dyeing_amount"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            df_display = df[final_cols].rename(columns=col_map)
            
            # 엑셀 및 인쇄 버튼
            c_exp1, c_exp2 = st.columns([1, 5])
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            c_exp1.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"염색완료내역_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # 인쇄 옵션 설정
            with st.expander("🖨️ 인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="염색 완료 내역", key="dd_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="dd_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="dd_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="dd_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="dd_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="dd_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="dd_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="dd_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="dd_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="dd_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="dd_mr")
                
                po_c12, po_c13 = st.columns(2)
                dd_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="dd_bo")
                dd_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="dd_bi")

            # [수정] utils의 generate_report_html 함수 사용 (오류 원천 차단)
            if c_exp2.button("🖨️ 인쇄하기", key="btn_print_dd"):
                options = {
                    'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                    'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                    'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none",
                    'bo': dd_bo, 'bi': dd_bi
                }
                summary_text = f"합계 - 수량: {total_stock:,}장 / 중량: {total_weight:,.1f}kg / 금액: {total_amount:,}원"
                print_html = generate_report_html(p_title, df_display, summary_text, options)
                st.components.v1.html(print_html, height=0, width=0)

            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(df_display, width="stretch", on_select="rerun", selection_mode="single-row", key=f"df_dye_done_{st.session_state['key_dyeing_done']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                current_status = sel_row.get('status', '')
                if current_status != "염색완료":
                    st.error(f"⛔ 현재 상태가 '**{current_status}**'이므로 이 단계에서 수정하거나 취소할 수 없습니다.")
                    st.info("다음 공정(봉제)이 이미 진행된 경우, 해당 공정에서 작업을 취소하여 상태를 되돌린 후 시도해주세요.")
                else:
                    st.markdown(f"### 완료 정보 수정: **{sel_row['name']}**")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        with st.form("dyeing_done_edit"):
                            st.write("입고 정보 수정")
                            new_in_date = st.date_input("염색완료일", datetime.datetime.strptime(sel_row['dyeing_in_date'], "%Y-%m-%d").date() if sel_row.get('dyeing_in_date') else datetime.date.today())
                            
                            c_e1, c_e2 = st.columns(2)
                            new_stock = c_e1.number_input("입고수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                            new_weight = c_e2.number_input("입고중량(kg)", value=float(sel_row.get('dyeing_in_weight', 0)) if not pd.isna(sel_row.get('dyeing_in_weight')) else 0.0, step=0.1, format="%.1f")
                            
                            c_e3, c_e4 = st.columns(2)
                            new_price = c_e3.number_input("단가(원)", value=int(sel_row.get('dyeing_unit_price', 0)) if not pd.isna(sel_row.get('dyeing_unit_price')) else 0, step=1)
                            
                            if st.form_submit_button("수정 저장"):
                                # 부가세 로직은 복잡하므로 여기서는 단순 계산만 반영
                                new_amount = int(new_weight * new_price)
                                db.collection("orders").document(sel_id).update({
                                    "dyeing_in_date": str(new_in_date),
                                    "stock": new_stock,
                                    "dyeing_in_weight": new_weight,
                                    "dyeing_unit_price": new_price,
                                    "dyeing_amount": new_amount
                                })
                                st.success("수정되었습니다.")
                                st.session_state["key_dyeing_done"] += 1
                                st.rerun()
                    with c2:
                        st.write("**완료 취소**")
                        st.warning("상태를 다시 '염색중'으로 되돌립니다.")
                        if st.button("완료 취소 (염색중으로 복귀)", type="primary"):
                            db.collection("orders").document(sel_id).update({
                                "status": "염색중"
                            })
                            st.success("복귀되었습니다.")
                            st.session_state["key_dyeing_done"] += 1
                            st.rerun()
        else:
            st.info("염색 완료된 내역이 없습니다.")

    # --- 4. 색번 설정 탭 ---
    elif sub_menu == "색번 설정":
        st.subheader("색번 관리")
        st.info("염색 출고 시 사용할 색번과 색상명을 관리합니다. (예: 명칭 '신백색' / 코드 'W0041')")
        manage_code_with_code("color_codes", [], "색번")
