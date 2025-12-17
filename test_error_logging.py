#!/usr/bin/env python3
"""
測試腳本：驗證錯誤儲存功能
"""
import json
from pathlib import Path
from procedura_sdk.metrics import get_metrics

def test_error_logging():
    """測試錯誤儲存到 errors.json"""
    
    # 模擬一個錯誤回應
    error_response = {
        "status": "error",
        "message": "auth failed: Invalid password"
    }
    
    print("測試錯誤儲存功能...")
    print(f"錯誤資料: {json.dumps(error_response, indent=2)}")
    
    # 儲存錯誤
    metrics = get_metrics()
    metrics.save_error(error_response)
    
    print("\n✓ 錯誤已儲存")
    
    # 檢查檔案是否存在
    errors_file = Path("runtime_ram/errors.json")
    if errors_file.exists():
        print(f"\n✓ errors.json 已建立在: {errors_file.absolute()}")
        
        # 讀取並顯示內容
        with open(errors_file, "r", encoding="utf-8") as f:
            errors = json.load(f)
        
        print(f"\n目前儲存的錯誤數量: {len(errors)}")
        print("\n最新的錯誤記錄:")
        print(json.dumps(errors[-1], indent=2, ensure_ascii=False))
    else:
        print(f"\n✗ errors.json 未找到")

def test_multiple_errors():
    """測試儲存多個錯誤"""
    
    errors = [
        {"status": "error", "message": "Connection timeout"},
        {"status": "error", "message": "Invalid token", "code": "AUTH_ERROR"},
        {"status": "error", "message": "Module not found", "module": "test_module"},
    ]
    
    print("\n\n測試儲存多個錯誤...")
    metrics = get_metrics()
    
    for i, err in enumerate(errors, 1):
        metrics.save_error(err)
        print(f"✓ 錯誤 {i} 已儲存")
    
    # 驗證
    errors_file = Path("runtime_ram/errors.json")
    if errors_file.exists():
        with open(errors_file, "r", encoding="utf-8") as f:
            saved_errors = json.load(f)
        print(f"\n總共儲存的錯誤數量: {len(saved_errors)}")

def test_empty_world_detection():
    """測試空世界檢測"""
    print("\n\n測試空世界檢測 (worldstate_snapshot with empty entities)...")
    
    # 模擬 worldstate_snapshot 回應但 entities 是空的
    empty_world_response = {
        "status": "error",
        "code": "EMPTY_WORLD",
        "message": "World not initialized: entities is empty",
        "cmd": "worldstate_snapshot",
        "result": {
            "meta": {"version": 3},
            "entities": {},  # 空的 entities
            "location": {},
            "environment": {}
        }
    }
    
    metrics = get_metrics()
    metrics.save_error(empty_world_response)
    print("✓ 空世界錯誤已儲存")
    
    # 顯示最新錯誤
    errors_file = Path("runtime_ram/errors.json")
    if errors_file.exists():
        with open(errors_file, "r", encoding="utf-8") as f:
            saved_errors = json.load(f)
        print("\n最新的空世界錯誤記錄:")
        print(json.dumps(saved_errors[-1], indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_error_logging()
    test_multiple_errors()
    test_empty_world_detection()
