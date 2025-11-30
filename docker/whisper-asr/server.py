"""
Whisper ASR Server - FastAPI-based Speech Recognition API
Compatible with openai-whisper-asr-webservice API format
"""

import os
import tempfile
import logging
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import torch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment configuration
ASR_MODEL = os.getenv("ASR_MODEL", "base")
ASR_ENGINE = os.getenv("ASR_ENGINE", "openai_whisper")
ASR_MODEL_PATH = os.getenv("ASR_MODEL_PATH", "/data/whisper")

# Global model instance
model = None

app = FastAPI(
    title="Whisper ASR API",
    description="Speech-to-Text API using OpenAI Whisper",
    version="1.0.0"
)


def get_model():
    """Load and cache the Whisper model."""
    global model
    if model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading Whisper model '{ASR_MODEL}' on device '{device}'...")

        if ASR_ENGINE == "faster_whisper":
            from faster_whisper import WhisperModel
            compute_type = "float16" if device == "cuda" else "int8"
            model = WhisperModel(
                ASR_MODEL,
                device=device,
                compute_type=compute_type,
                download_root=ASR_MODEL_PATH
            )
        else:
            import whisper
            model = whisper.load_model(ASR_MODEL, device=device, download_root=ASR_MODEL_PATH)

        logger.info(f"Model loaded successfully using {ASR_ENGINE} engine")
    return model


@app.on_event("startup")
async def startup_event():
    """Preload model on startup."""
    logger.info("Starting Whisper ASR Server...")
    logger.info(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        logger.info(f"CUDA device: {torch.cuda.get_device_name(0)}")
    get_model()


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model": ASR_MODEL,
        "engine": ASR_ENGINE,
        "cuda_available": torch.cuda.is_available()
    }


@app.post("/asr")
async def transcribe(
    audio_file: UploadFile = File(...),
    task: str = Form("transcribe"),
    language: Optional[str] = Form(None),
    output: str = Form("json")
):
    """
    Transcribe audio file to text.

    Compatible with openai-whisper-asr-webservice API format.

    Args:
        audio_file: Audio file to transcribe
        task: 'transcribe' or 'translate'
        language: Language code (e.g., 'en', 'ko'). Auto-detect if not specified.
        output: Output format ('json', 'txt', 'vtt', 'srt')
    """
    if audio_file is None:
        raise HTTPException(status_code=400, detail="No audio file provided")

    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.filename)[1]) as tmp:
        content = await audio_file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        whisper_model = get_model()

        if ASR_ENGINE == "faster_whisper":
            segments, info = whisper_model.transcribe(
                tmp_path,
                task=task,
                language=language,
                beam_size=5
            )
            text = " ".join([segment.text for segment in segments])
            detected_language = info.language
        else:
            result = whisper_model.transcribe(
                tmp_path,
                task=task,
                language=language
            )
            text = result["text"]
            detected_language = result.get("language", language)

        if output == "txt":
            return JSONResponse(content=text, media_type="text/plain")

        return {
            "text": text.strip(),
            "language": detected_language,
            "task": task
        }

    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up temporary file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/detect-language")
async def detect_language(audio_file: UploadFile = File(...)):
    """Detect the language of an audio file."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.filename)[1]) as tmp:
        content = await audio_file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        whisper_model = get_model()

        if ASR_ENGINE == "faster_whisper":
            _, info = whisper_model.transcribe(tmp_path)
            return {"detected_language": info.language, "language_probability": info.language_probability}
        else:
            import whisper
            audio = whisper.load_audio(tmp_path)
            audio = whisper.pad_or_trim(audio)
            mel = whisper.log_mel_spectrogram(audio).to(whisper_model.device)
            _, probs = whisper_model.detect_language(mel)
            detected_lang = max(probs, key=probs.get)
            return {"detected_language": detected_lang, "language_probability": probs[detected_lang]}

    except Exception as e:
        logger.error(f"Language detection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
