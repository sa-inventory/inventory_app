import streamlit as st
import pandas as pd
import datetime
import io
from firebase_admin import firestore
from utils import get_partners, generate_report_html

def render_sewing(db, sub_menu):
    st.header("봉제 현황")
    st.info("염색이 완료된 원단을 봉제하여 완제품으로 만듭니다.")
    
    sewing_partners = get_partners("봉제업체")
    
    # --- 1. 봉제 대기 탭 ---
    if sub_menu == "봉제 대기 목록":
        st.subheader("봉제 대기 목록 (염색완료)")
        
        # [NEW] 목록 갱신을 위한 키 초기화 (봉제대기)
        if "key_sewing_wait" not in st.session_state:
            st.session_state["key_sewing_wait"] = 0
            
        docs = db.collection("orders").where("status", "==", "염색완료").stream()
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
                "color": "색상", "stock": "수량(장)", "dyeing_partner": "염색처", "date": "접수일", "note": "비고"
            }
            display_cols = ["order_no", "customer", "name", "color", "stock", "dyeing_partner", "date", "note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            # [NEW] 인쇄 옵션 설정 (봉제작업지시서)
            with st.expander("봉제작업지시서 인쇄 옵션"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="봉제 작업 지시서", key="si_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="si_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=12, step=1, key="si_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=10, step=1, key="si_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="si_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="si_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="si_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="si_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="si_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="si_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="si_mr")
                
                po_c12, po_c13 = st.columns(2)
                si_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="si_bo")
                si_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="si_bi")

            # [수정] 버튼을 테이블 우측 상단으로 이동
            c_head, c_btn = st.columns([0.85, 0.15])
            with c_head:
                st.write("🔽 봉제 작업할 항목을 선택하세요. (다중 선택 가능)")
            with c_btn:
                btn_print_inst = st.button("🖨️ 봉제작업지시서", use_container_width=True)

            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="multi-row", key=f"df_sew_wait_{st.session_state['key_sewing_wait']}")
            
            # [수정] 인쇄 로직 분리
            if btn_print_inst:
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    selected_rows = df.iloc[selected_indices]
                    
                    # 인쇄용 데이터 준비
                    print_df = selected_rows.copy()
                    # 참고사항 컬럼 추가 (빈 칸)
                    print_df['참고사항'] = " " * 30 
                    
                    # 인쇄할 컬럼 매핑
                    p_cols_map = {
                        "order_no": "발주번호", "customer": "발주처", "name": "제품명", 
                        "color": "색상", "stock": "수량", "note": "비고", "참고사항": "참고사항"
                    }
                    # note 컬럼이 없으면 생성
                    if 'note' not in print_df.columns: print_df['note'] = ""
                    
                    p_cols = ["order_no", "customer", "name", "color", "stock", "note", "참고사항"]
                    p_final_cols = [c for c in p_cols if c in print_df.columns]
                    
                    df_print_view = print_df[p_final_cols].rename(columns=p_cols_map)
                    
                    # 인쇄 옵션
                    options = {
                        'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                        'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                        'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none",
                        'bo': si_bo, 'bi': si_bi
                    }
                    html = generate_report_html(p_title, df_print_view, f"총 {len(print_df)}건", options)
                    st.components.v1.html(html, height=0, width=0)
                else:
                    st.warning("출력할 항목을 선택해주세요.")

            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]

                # [기존] 봉제 시작 (단일 선택 시에만 표시)
                if len(selected_indices) == 1:
                    idx = selected_indices[0]
                    sel_row = df.iloc[idx]
                    sel_id = sel_row['id']
                    current_stock = int(sel_row.get('stock', 0))
                    
                    st.divider()
                    st.markdown(f"### 봉제 작업 시작: **{sel_row['name']}**")
                    
                    # st.form 제거 (라디오 버튼 즉시 반응을 위해)
                    c1, c2 = st.columns(2)
                    s_date = c1.date_input("봉제시작일", datetime.date.today())
                    s_type = c2.radio("작업 구분", ["자체봉제", "외주봉제"], horizontal=True, key=f"s_type_{sel_id}")
                    
                    c3, c4 = st.columns(2)
                    s_partner = c3.selectbox("봉제업체", sewing_partners if sewing_partners else ["직접입력"], disabled=(s_type=="자체봉제"), key=f"s_partner_{sel_id}")
                    s_qty = c4.number_input("작업 수량(장)", min_value=1, max_value=current_stock, value=current_stock, step=10, help="일부 수량만 작업하려면 숫자를 줄이세요.", key=f"s_qty_{sel_id}")
                    
                    if st.button("봉제 시작", key=f"btn_start_sew_{sel_id}"):
                        # 수량 분할 로직
                        if s_qty < current_stock:
                            # 1. 분할된 새 문서 생성 (작업분)
                            doc_snapshot = db.collection("orders").document(sel_id).get()
                            new_doc_data = doc_snapshot.to_dict().copy()
                            new_doc_data['stock'] = s_qty
                            new_doc_data['status'] = "봉제중"
                            new_doc_data['sewing_type'] = s_type
                            new_doc_data['sewing_start_date'] = str(s_date)
                            if s_type == "외주봉제":
                                new_doc_data['sewing_partner'] = s_partner
                            else:
                                new_doc_data['sewing_partner'] = "자체"
                            
                            db.collection("orders").add(new_doc_data)
                            
                            # 2. 원본 문서 업데이트 (잔여분)
                            db.collection("orders").document(sel_id).update({
                                "stock": current_stock - s_qty
                            })
                            st.success(f"{s_qty}장 분할하여 봉제 작업을 시작합니다. (잔여: {current_stock - s_qty}장)")
                        else:
                            # 전체 작업
                            updates = {
                                "status": "봉제중",
                                "sewing_type": s_type,
                                "sewing_start_date": str(s_date)
                            }
                            if s_type == "외주봉제":
                                updates['sewing_partner'] = s_partner
                            else:
                                updates['sewing_partner'] = "자체"
                                
                            db.collection("orders").document(sel_id).update(updates)
                            st.success("봉제 작업을 시작합니다.")
                        
                        st.session_state["key_sewing_wait"] += 1 # 목록 선택 초기화
                        st.rerun()
                elif len(selected_indices) > 1:
                    st.info("ℹ️ 봉제 시작 처리는 한 번에 하나의 항목만 가능합니다. (작업지시서는 다중 출력 가능)")
        else:
            st.info("봉제 대기 중인 건이 없습니다.")
            
    # --- 2. 봉제중 탭 ---
    elif sub_menu == "봉제중 목록":
        st.subheader("봉제중 목록")
        
        # [NEW] 목록 갱신을 위한 키 초기화
        if "sewing_ing_key" not in st.session_state:
            st.session_state["sewing_ing_key"] = 0
            
        docs = db.collection("orders").where("status", "==", "봉제중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            col_map = {
                "order_no": "발주번호", "sewing_partner": "봉제처", "sewing_type": "구분",
                "name": "제품명", "color": "색상", "stock": "수량", "sewing_start_date": "시작일"
            }
            display_cols = ["sewing_start_date", "sewing_type", "sewing_partner", "order_no", "name", "color", "stock"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 완료 처리할 항목을 선택하세요.")
            # [수정] 동적 키 적용하여 완료 후 선택 해제
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="single-row", key=f"df_sew_ing_{st.session_state['sewing_ing_key']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                
                # [FIX] 선택된 인덱스가 데이터프레임 범위를 벗어나는 경우 방지
                if idx >= len(df):
                    st.rerun()
                
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 봉제 완료 처리: **{sel_row['name']}**")
                
                tab_act1, tab_act2 = st.tabs(["봉제 완료 처리", "정보 수정 / 취소"])
                
                with tab_act1:
                    st.write("봉제 완료 정보를 입력하세요.")
                    c1, c2, c3 = st.columns(3)
                    s_end_date = c1.date_input("봉제완료일", datetime.date.today())
                    s_real_stock = c2.number_input("완료수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                    s_defect_stock = c3.number_input("불량수량(장)", min_value=0, step=1, value=0, help="불량으로 빠지는 수량입니다.")
                    
                    # 외주봉제일 경우 단가/금액 입력
                    s_price = 0
                    s_total = 0
                    s_supply = 0
                    s_vat = 0
                    s_vat_inc = False
                    
                    if sel_row.get('sewing_type') == "외주봉제":
                        st.markdown("#### 외주 가공비 정산")
                        c3, c4 = st.columns(2)
                        s_price = c3.number_input("봉제단가(원)", min_value=0, step=1)
                        s_vat_inc = c4.checkbox("부가세 포함", value=False, key="sew_vat_check")
                        
                        base_calc = int(s_real_stock * s_price)
                        if s_vat_inc:
                            s_supply = int(base_calc / 1.1)
                            s_vat = base_calc - s_supply
                            s_total = base_calc
                        else:
                            s_supply = base_calc
                            s_vat = int(base_calc * 0.1)
                            s_total = base_calc + s_vat
                            
                        st.info(f"**봉제비용 합계**: {s_total:,}원 (공급가: {s_supply:,}원 / 부가세: {s_vat:,}원)")
                    
                    if st.button("봉제 완료 (출고대기로 이동)"):
                        # [수정] 불량 수량을 제외한 정품 수량만 다음 공정(출고)으로 이동
                        final_stock = max(0, s_real_stock - s_defect_stock)
                        
                        updates = {
                            "status": "봉제완료",
                            "sewing_end_date": str(s_end_date),
                            "stock": s_real_stock,
                            "stock": final_stock,
                            "sewing_defect_qty": s_defect_stock # 불량 수량 저장
                        }
                        if sel_row.get('sewing_type') == "외주봉제":
                            updates["sewing_unit_price"] = s_price
                            updates["sewing_amount"] = s_total
                            updates["sewing_supply"] = s_supply
                            updates["sewing_vat"] = s_vat
                            updates["vat_included"] = s_vat_inc
                        
                        db.collection("orders").document(sel_id).update(updates)
                        st.success("봉제 완료 처리되었습니다.")
                        st.session_state["sewing_ing_key"] += 1 # 키 증가로 목록 선택 초기화
                        st.rerun()
                            
                with tab_act2:
                    with st.form("sewing_edit_form"):
                        st.write("작업 정보 수정")
                        c1, c2 = st.columns(2)
                        e_date = c1.date_input("봉제시작일", datetime.datetime.strptime(sel_row['sewing_start_date'], "%Y-%m-%d").date() if sel_row.get('sewing_start_date') else datetime.date.today())
                        e_type = c2.radio("작업 구분", ["자체봉제", "외주봉제"], horizontal=True, index=0 if sel_row.get('sewing_type') == "자체봉제" else 1)
                        
                        e_partner = st.selectbox("봉제업체", sewing_partners if sewing_partners else ["직접입력"], index=sewing_partners.index(sel_row['sewing_partner']) if sel_row.get('sewing_partner') in sewing_partners else 0)
                        
                        if st.form_submit_button("수정 저장"):
                            updates = {
                                "sewing_start_date": str(e_date),
                                "sewing_type": e_type,
                                "sewing_partner": "자체" if e_type == "자체봉제" else e_partner
                            }
                            db.collection("orders").document(sel_id).update(updates)
                            st.success("수정되었습니다.")
                            st.session_state["sewing_ing_key"] += 1
                            st.rerun()
                    
                    st.markdown("#### 작업 취소")
                    if st.button("봉제 취소 (대기로 되돌리기)", type="primary"):
                        # [NEW] 병합 로직: 같은 발주번호의 대기중(염색완료)인 항목이 있으면 합침
                        siblings = list(db.collection("orders")\
                            .where("order_no", "==", sel_row['order_no'])\
                            .where("status", "==", "염색완료")\
                            .stream())
                        
                        merged = False
                        for sib in siblings:
                            sib_data = sib.to_dict()
                            # 안전장치: 제품코드와 색상이 같은지 확인 (발주번호가 같으면 보통 같음)
                            if sib_data.get('product_code') == sel_row.get('product_code') and \
                               sib_data.get('color') == sel_row.get('color'):
                                
                                new_stock = int(sib_data.get('stock', 0)) + int(sel_row.get('stock', 0))
                                db.collection("orders").document(sib.id).update({"stock": new_stock})
                                db.collection("orders").document(sel_id).delete()
                                merged = True
                                st.success(f"기존 대기 건과 병합되어 '염색완료' 상태로 복귀되었습니다. (합계: {new_stock}장)")
                                break
                        
                        if not merged:
                            db.collection("orders").document(sel_id).update({"status": "염색완료"})
                            st.success("취소되었습니다. (염색완료 상태로 복귀)")
                        
                        st.session_state["sewing_ing_key"] += 1
                        st.rerun()
        else:
            st.info("현재 봉제 중인 작업이 없습니다.")

    # --- 3. 봉제 완료 탭 ---
    elif sub_menu == "봉제 완료 목록":
        st.subheader("봉제 완료 목록")
        
        if "key_sewing_done" not in st.session_state:
            st.session_state["key_sewing_done"] = 0
        
        # 검색 및 엑셀 다운로드
        with st.expander("검색", expanded=True):
            with st.form("search_sew_done"):
                c1, c2, c3 = st.columns([2, 1, 1])
                today = datetime.date.today()
                s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
                s_partner = c2.text_input("봉제업체")
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
        target_statuses = ["봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 날짜 필터
            s_end = d.get('sewing_end_date')
            if s_end:
                try:
                    s_end_obj = datetime.datetime.strptime(s_end, "%Y-%m-%d")
                    if not (start_dt <= s_end_obj <= end_dt): continue
                except: continue
            else: continue
            
            # 업체 필터
            if s_partner and s_partner not in d.get('sewing_partner', ''):
                continue

            # 발주처 필터
            if s_customer and s_customer not in d.get('customer', ''):
                continue
                
            rows.append(d)
            
        rows.sort(key=lambda x: x.get('sewing_end_date', ''), reverse=True)
        
        if rows:
            df = pd.DataFrame(rows)
            
            # 합계 계산
            total_stock = df['stock'].sum() if 'stock' in df.columns else 0
            total_amount = df['sewing_amount'].sum() if 'sewing_amount' in df.columns else 0
            
            st.markdown(f"### 📊 합계: 수량 **{total_stock:,}장** / 금액 **{total_amount:,}원**")
            
            col_map = {
                "order_no": "발주번호", "sewing_partner": "봉제처", "sewing_end_date": "완료일",
                "name": "제품명", "color": "색상", "stock": "수량", "sewing_type": "구분",
                "sewing_unit_price": "단가", "sewing_amount": "금액", "sewing_defect_qty": "불량",
                "customer": "발주처"
            }
            display_cols = ["sewing_end_date", "sewing_type", "sewing_partner", "customer", "order_no", "name", "color", "stock", "sewing_defect_qty", "sewing_unit_price", "sewing_amount"]
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
                file_name=f"봉제완료내역_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # 인쇄 옵션 설정
            with st.expander("🖨️ 인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="봉제 완료 내역", key="sd_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="sd_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="sd_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="sd_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="sd_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="sd_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="sd_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="sd_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="sd_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="sd_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="sd_mr")
                
                po_c12, po_c13 = st.columns(2)
                sd_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="sd_bo")
                sd_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="sd_bi")

            # [수정] utils의 generate_report_html 함수 사용
            if c_exp2.button("🖨️ 바로 인쇄하기", key="btn_print_sd"):
                options = {
                    'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                    'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                    'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none",
                    'bo': sd_bo, 'bi': sd_bi
                }
                summary_text = f"합계 - 수량: {total_stock:,}장 / 금액: {total_amount:,}원"
                print_html = generate_report_html(p_title, df_display, summary_text, options)
                st.components.v1.html(print_html, height=0, width=0)

            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(df_display, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key=f"df_sew_done_{st.session_state['key_sewing_done']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]

                # [FIX] 선택된 인덱스가 데이터프레임 범위를 벗어나는 경우를 방지 (삭제/상태변경 후 발생)
                if idx >= len(df):
                    # 선택 상태를 초기화하기 위해 리런
                    st.rerun()

                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                current_status = sel_row.get('status', '')
                if current_status != "봉제완료":
                    st.error(f"⛔ 현재 상태가 '**{current_status}**'이므로 이 단계에서 수정하거나 취소할 수 없습니다.")
                    st.info("이미 출고 처리가 된 경우, 출고 현황에서 출고를 취소해야 합니다.")
                else:
                    st.markdown(f"### 완료 정보 수정: **{sel_row['name']}**")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        with st.form("sewing_done_edit"):
                            st.write("완료 정보 수정")
                            new_end_date = st.date_input("봉제완료일", datetime.datetime.strptime(sel_row['sewing_end_date'], "%Y-%m-%d").date() if sel_row.get('sewing_end_date') else datetime.date.today())
                            new_stock = st.number_input("완료수량(정품)", value=int(sel_row.get('stock', 0)), step=10)
                            new_defect = st.number_input("불량수량(장)", value=int(sel_row.get('sewing_defect_qty', 0)), step=1)
                            
                            new_price = 0
                            if sel_row.get('sewing_type') == "외주봉제":
                                new_price = st.number_input("봉제단가(원)", value=int(sel_row.get('sewing_unit_price', 0)) if not pd.isna(sel_row.get('sewing_unit_price')) else 0, step=1)
                            
                            if st.form_submit_button("수정 저장"):
                                updates = {
                                    "sewing_end_date": str(new_end_date),
                                    "stock": new_stock,
                                    "sewing_defect_qty": new_defect
                                }
                                if sel_row.get('sewing_type') == "외주봉제":
                                    # 부가세 로직은 복잡하므로 단순 계산만 반영
                                    updates["sewing_unit_price"] = new_price
                                    updates["sewing_amount"] = int(new_stock * new_price)
                                    
                                db.collection("orders").document(sel_id).update(updates)
                                st.success("수정되었습니다.")
                                st.session_state["key_sewing_done"] += 1
                                st.rerun()
                    with c2:
                        st.write("**완료 취소**")
                        st.warning("상태를 다시 '봉제중'으로 되돌립니다.")
                        if st.button("완료 취소 (봉제중으로 복귀)", type="primary"):
                            db.collection("orders").document(sel_id).update({"status": "봉제중"})
                            st.success("복귀되었습니다.")
                            st.session_state["key_sewing_done"] += 1
                            st.rerun()
        else:
            st.info("조회된 봉제 완료 내역이 없습니다.")
