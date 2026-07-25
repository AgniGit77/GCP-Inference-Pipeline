"""
Prediction validator — checks predictions.json against the output schema
and validates manifest scene coverage.
"""

import argparse
import json
import sys


def validate_predictions(predictions_path: str, manifest_path: str = None) -> bool:
    """Validate predictions.json structure and manifest coverage."""
    errors = []

    # Load predictions
    try:
        with open(predictions_path, "r") as f:
            predictions = json.load(f)
    except Exception as e:
        print(f"ERROR: Cannot load predictions: {e}")
        return False

    # Check schema version
    if predictions.get("schema_version") != "1.0":
        errors.append(f"schema_version must be '1.0', got '{predictions.get('schema_version')}'")

    # Check scenes
    if "scenes" not in predictions:
        errors.append("Missing 'scenes' key")
        for e in errors:
            print(f"ERROR: {e}")
        return False

    pred_scene_ids = set()
    for scene in predictions["scenes"]:
        sid = scene.get("scene_id")
        if sid is None:
            errors.append("Scene missing 'scene_id'")
            continue

        if sid in pred_scene_ids:
            errors.append(f"Duplicate scene_id: {sid}")
        pred_scene_ids.add(sid)

        if "detections" not in scene:
            errors.append(f"Scene {sid} missing 'detections' key")
            continue

        for i, det in enumerate(scene["detections"]):
            # Check required fields
            for field in ["pixel_x", "pixel_y", "longitude", "latitude", "confidence"]:
                if field not in det:
                    errors.append(f"Scene {sid} detection {i}: missing '{field}'")

            # Check confidence range
            conf = det.get("confidence")
            if conf is not None:
                if not isinstance(conf, (int, float)):
                    errors.append(f"Scene {sid} detection {i}: confidence must be numeric")
                elif conf < 0 or conf > 1:
                    errors.append(f"Scene {sid} detection {i}: confidence {conf} not in [0, 1]")
                elif not (conf == conf):  # NaN check
                    errors.append(f"Scene {sid} detection {i}: confidence is NaN")

            # Check coordinates are finite
            for coord in ["pixel_x", "pixel_y", "longitude", "latitude"]:
                val = det.get(coord)
                if val is not None:
                    if not isinstance(val, (int, float)):
                        errors.append(f"Scene {sid} detection {i}: {coord} must be numeric")
                    elif val != val:  # NaN check
                        errors.append(f"Scene {sid} detection {i}: {coord} is NaN")

    # Check manifest coverage
    if manifest_path:
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            manifest_ids = {s["scene_id"] for s in manifest["scenes"]}

            missing = manifest_ids - pred_scene_ids
            extra = pred_scene_ids - manifest_ids

            if missing:
                errors.append(f"Missing scenes from manifest: {missing}")
            if extra:
                errors.append(f"Unknown scenes not in manifest: {extra}")
        except Exception as e:
            print(f"WARNING: Cannot validate manifest coverage: {e}")

    # Report results
    if errors:
        print(f"VALIDATION FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  ERROR: {e}")
        return False
    else:
        total_dets = sum(len(s.get("detections", [])) for s in predictions["scenes"])
        print(f"VALIDATION PASSED: {len(predictions['scenes'])} scenes, {total_dets} total detections")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate predictions.json")
    parser.add_argument("predictions", help="Path to predictions.json")
    parser.add_argument("--manifest", help="Path to manifest.json for scene coverage check")
    args = parser.parse_args()

    if not validate_predictions(args.predictions, args.manifest):
        sys.exit(1)
