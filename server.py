from flask import Flask, request, Response
from io import BytesIO
import torch
from av import open as avopen
from typing import Dict, List

import utils
from infer import infer, get_net_g, latest_version
from scipy.io import wavfile

from config import config

# Flask Init
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


def replace_punctuation(text, i=2):
    punctuation = "，。？！"
    for char in punctuation:
        text = text.replace(char, char * i)
    return text


def wav2(i, o, format):
    inp = avopen(i, "rb")
    out = avopen(o, "wb", format=format)
    if format == "ogg":
        format = "libvorbis"

    ostream = out.add_stream(format)

    for frame in inp.decode(audio=0):
        for p in ostream.encode(frame):
            out.mux(p)

    for p in ostream.encode(None):
        out.mux(p)

    out.close()
    inp.close()


net_g_List = []
hps_List = []
# 模型角色字典
# 使用方法 chr_name = chrsMap[model_id][chr_id]
chrsMap: List[Dict[int, str]] = list()

# 加载模型
models = config.server_config.models
for model in models:
    hps_List.append(utils.get_hparams_from_file(model["config"]))
    # 添加角色字典
    chrsMap.append(dict())
    for name, cid in hps_List[-1].data.spk2id.items():
        chrsMap[-1][cid] = name
    version = (
        hps_List[-1].version if hasattr(hps_List[-1], "version") else latest_version
    )
    net_g_List.append(
        get_net_g(
            model_path=model["model"],
            version=version,
            device=model["device"],
            hps=hps_List[-1],
        )
    )


@app.route("/")
def main():
    try:
        model = int(request.args.get("model"))
        speaker = request.args.get("speaker", "")  # 指定人物名
        speaker_id = request.args.get("speaker_id", None)  # 直接指定id
        text = request.args.get("text").replace("/n", "")
        sdp_ratio = float(request.args.get("sdp_ratio", 0.2))
        noise = float(request.args.get("noise", 0.5))
        noisew = float(request.args.get("noisew", 0.6))
        length = float(request.args.get("length", 1.2))
        language = request.args.get("language")
        if length >= 2:
            return "Too big length"
        if len(text) >= 250:
            return "Too long text"
        fmt = request.args.get("format", "wav")
        if None in (speaker, text):
            return "Missing Parameter"
        if fmt not in ("mp3", "wav", "ogg"):
            return "Invalid Format"
        if language not in ("JP", "ZH"):
            return "Invalid language"
    except:
        return "Invalid Parameter"

    if speaker_id is not None:
        if speaker_id.isdigit():
            speaker = chrsMap[model][int(speaker_id)]

    with torch.no_grad():
        audio = infer(
            text=text,
            sdp_ratio=sdp_ratio,
            noise_scale=noise,
            noise_scale_w=noisew,
            length_scale=length,
            sid=speaker,
            language=models[model]["language"],
            hps=hps_List[model],
            net_g=net_g_List[model],
            device=models[model]["device"],
        )

    with BytesIO() as wav:
        wavfile.write(wav, hps_List[model].data.sampling_rate, audio)
        torch.cuda.empty_cache()
        if fmt == "wav":
            return Response(wav.getvalue(), mimetype="audio/wav")
        wav.seek(0, 0)
        with BytesIO() as ofp:
            wav2(wav, ofp, fmt)
            return Response(
                ofp.getvalue(), mimetype="audio/mpeg" if fmt == "mp3" else "audio/ogg"
            )


if __name__ == "__main__":
    app.run(port=config.server_config.port)
