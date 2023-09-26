from aiohttp import web
from segment_anything import sam_model_registry, SamPredictor
from PIL import Image, ImageOps
import os
import requests
import folder_paths
import json
import numpy as np
import server

# For speeding up ONNX model, see https://github.com/facebookresearch/segment-anything/tree/main/demo#onnx-multithreading-with-sharedarraybuffer
def inject_headers(original_handler):
    async def _handler(request):
        res = await original_handler(request)
        res.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        res.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
        return res

    return _handler


routes = []
for item in server.PromptServer.instance.routes._items:
    if item.path == "/":
        item = web.RouteDef(
            method=item.method,
            path=item.path,
            handler=inject_headers(item.handler),
            kwargs=item.kwargs,
        )
    routes.append(item)
server.PromptServer.instance.routes._items = routes


@server.PromptServer.instance.routes.get("/sam_model")
async def get_sam_model(request):
    filename = os.path.join(folder_paths.base_path, "web/models/sam.onnx")
    # print(filename)
    if not os.path.isfile(filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        response = requests.get(
            "https://avatech-avatar-dev1.nyc3.cdn.digitaloceanspaces.com/models/sam.onnx"
        )
        response.raise_for_status()
        with open(filename, "wb") as f:
            f.write(response.content)
        print(f"ONNX model downloaded: {filename}")
    return web.FileResponse(filename)


def load_image(image):
    image_path = folder_paths.get_annotated_filepath(image)
    i = Image.open(image_path)
    i = ImageOps.exif_transpose(i)
    image = i.convert("RGB")
    image = np.array(image).astype(np.float32) / 255.0
    return image


@server.PromptServer.instance.routes.post("/sam_model")
async def post_sam_model(request):
    post = await request.json()
    emb_id = post.get("embedding_id")
    emb_filename = f"{folder_paths.get_output_directory()}/{emb_id}.npy"
    if not os.path.exists(emb_filename):
        image = load_image(post.get("image"))
        ckpt = post.get("ckpt")
        model_type = post.get("model_type")
        ckpt = folder_paths.get_full_path("sam", ckpt)
        sam = sam_model_registry[model_type](checkpoint=ckpt)
        predictor = SamPredictor(sam)

        image_np = (image * 255).astype(np.uint8)
        predictor.set_image(image_np)
        emb = predictor.get_image_embedding().cpu().numpy()
        np.save(emb_filename, emb)
        with open(f"{folder_paths.get_output_directory()}/{emb_id}.json", "w") as f:
            json.dump(
                {
                    "input_size": predictor.input_size,
                    "original_size": predictor.original_size,
                },
                f,
            )
    return web.json_response({})