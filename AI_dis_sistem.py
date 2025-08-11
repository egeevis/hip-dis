import os
import io
import json
import random
import streamlit as st

try:
    from docx import Document
except ImportError:
    Document = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

st.set_page_config(page_title="Hiperaktivist – Eğitim Dosyası Okuma Testi", page_icon="🧩", layout="wide")
st.title("📂 Eğitim & Teknik Dosyası Okuma Testi")
st.caption("Bu araç, yüklediğin dosyaların GPT’ye gerçekten iletilip iletilmediğini test eder.")

# ------------------------------
# API Key Ayarı
# ------------------------------
openai_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    value=os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", "")),
    key="openai_api_key_input"
)

# ------------------------------
# Yardımcı Fonksiyonlar
# ------------------------------
def read_file(file) -> str:
    name = file.name.lower()
    if name.endswith(".txt") or name.endswith(".md"):
        return file.read().decode("utf-8", errors="ignore")
    if name.endswith(".docx"):
        if not Document:
            return "(python-docx eksik)"
        buf = io.BytesIO(file.read())
        doc = Document(buf)
        return "\n".join([p.text for p in doc.paragraphs])
    if name.endswith(".pdf"):
        if not PyPDF2:
            return "(PyPDF2 eksik)"
        buf = io.BytesIO(file.read())
        reader = PyPDF2.PdfReader(buf)
        return "\n".join([p.extract_text() or "" for p in reader.pages])
    try:
        return file.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

def get_random_snippet(text, length=10):
    """Metinden rastgele bir snippet alır."""
    words = text.split()
    if len(words) <= length:
        return " ".join(words)
    start = random.randint(0, len(words) - length)
    return " ".join(words[start:start + length])

# ------------------------------
# OpenAI Client
# ------------------------------
client = None
if openai_key and OpenAI:
    try:
        client = OpenAI(api_key=openai_key)
    except Exception as e:
        st.sidebar.error(f"OpenAI istemcisi başlatılamadı: {e}")

# ------------------------------
# Dosya Yükleme
# ------------------------------
edu_file = st.file_uploader("📘 Eğitim Dosyası", type=["docx", "pdf", "txt", "md"], key="edu")
ty_file = st.file_uploader("🛠 Teknik & Yöntemler Dosyası", type=["docx", "pdf", "txt", "md"], key="ty")

edu_text, tech_text = "", ""
if edu_file:
    edu_text = read_file(edu_file)
if ty_file:
    tech_text = read_file(ty_file)

# Önizleme
if edu_text:
    st.subheader("📘 Eğitim Dosyası İçeriği (ilk 500 karakter)")
    st.code(edu_text[:500])
if tech_text:
    st.subheader("🛠 Teknik & Yöntemler Dosyası İçeriği (ilk 500 karakter)")
    st.code(tech_text[:500])

# ------------------------------
# Debug Test
# ------------------------------
if st.button("🚀 GPT Okuma Testi Yap"):
    if not client:
        st.error("API anahtarı girilmedi.")
    elif not edu_text and not tech_text:
        st.error("En az bir dosya yüklemelisin.")
    else:
        with st.spinner("GPT’ye test sorusu gönderiliyor..."):
            # Eğitim dosyasından rastgele bir snippet seçelim
            combined_text = (edu_text + "\n" + tech_text).strip()
            snippet = get_random_snippet(combined_text, length=8)

            system_prompt = f"""
Sen bir test asistanısın. Sana verilen metinleri dikkatle oku.
Az sonra sana metinlerden alınmış küçük bir parça göstereceğim.
Görevin: Bu parçanın gerçekten sana verilen metinlerde geçip geçmediğini söylemek.
""".strip()

            user_prompt = f"""
# METİNLER
{combined_text}

# TEST PARÇASI
"{snippet}"

Bu parça yukarıdaki metinlerde geçiyor mu? Evet ya da hayır olarak cevap ver ve hangi bağlamda geçtiğini açıkla.
"""

            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                )
                answer = resp.choices[0].message.content.strip()
                st.success("✅ GPT’den Yanıt Alındı")
                st.write("**Seçilen snippet:**", snippet)
                st.markdown("---")
                st.write(answer)
            except Exception as e:
                st.error(f"OpenAI hatası: {e}")
