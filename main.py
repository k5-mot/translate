"""将来の接続形を示すStreamlit UIモック。"""

import streamlit as st

st.set_page_config(page_title="Translate", page_icon="🌐", layout="wide")
st.title("🌐 Translate")
st.caption("画面モックです。Pipeline、外部endpoint、成果物保存には接続していません。")

translate_tab, review_tab, register_tab = st.tabs(["Translate", "Review", "Register"])

with translate_tab:
    st.file_uploader("英語PDF", type=["pdf"], key="translate-source")
    st.selectbox("翻訳backend", ["llm", "libretranslate"])
    st.button("翻訳を開始", disabled=True)

with review_tab:
    st.file_uploader("英語原文PDF", type=["pdf"], key="review-source")
    st.file_uploader("日本語訳文PDF", type=["pdf"], key="review-translation")
    st.button("レビューを開始", disabled=True)

with register_tab:
    st.file_uploader(
        "参考資料",
        type=["pdf", "docx", "pptx", "md", "markdown", "txt"],
        accept_multiple_files=True,
    )
    st.text_input("source_id")
    st.button("登録を開始", disabled=True)

st.subheader("固定された進捗例")
st.progress(0.65, text="TRANSLATE: 13 / 20 calls")
st.code(
    "outputs/sample/0195f6b0-7c00-7000-8000-000000000000/publisher/docx/document.ja.docx"
)
st.info("TODO: Streamlit UIをPipeline、Resume、Artifact表示へ接続する。")
