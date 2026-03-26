import ddddocr
from PIL import Image
import os
import json

def recognize_captcha(image_path, box):
    """
    使用 ddddocr 识别指定区域的验证码
    
    Args:
        image_path: 全屏截图路径
        box: 包含 x, y, width, height 的字典
    
    Returns:
        识别出的字符串
    """
    if not os.path.exists(image_path):
        return "Error: Screenshot not found"

    # 打开图片
    img = Image.open(image_path)
    
    # 裁剪图片 (left, top, right, bottom)
    left = box['x']
    top = box['y']
    right = left + box['width']
    bottom = top + box['height']
    
    # 注意：Playwright 的坐标通常是逻辑像素，可能需要考虑 Device Pixel Ratio
    # 但 agent-browser 的 screenshot 通常与 get box 的坐标系一致
    cropped_img = img.crop((left, top, right, bottom))
    
    # 保存临时裁剪图便于调试 (可选)
    temp_crop_path = image_path.replace(".png", "_crop.png")
    cropped_img.save(temp_crop_path)
    
    # 使用 ddddocr 识别
    ocr = ddddocr.DdddOcr(show_ad=False)
    with open(temp_crop_path, 'rb') as f:
        img_bytes = f.read()
    
    res = ocr.classification(img_bytes)
    return res
