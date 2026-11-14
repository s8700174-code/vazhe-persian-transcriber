"""Download original Persian-v4 weights (or convert a local copy) to CTranslate2."""
import argparse
import os
from pathlib import Path

os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ['HF_HUB_DISABLE_XET'] = '1'
ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', help='Folder with manually downloaded original model files')
    args = parser.parse_args()
    if not args.source:
        os.environ.pop('HF_HUB_OFFLINE', None)
    from ctranslate2.converters import TransformersConverter
    from transformers import AutoTokenizer
    target = ROOT / 'models' / 'persian-v4-ct2'
    if (target / 'model.bin').exists():
        print('Model already converted. No files overwritten.')
        return
    if args.source:
        source_path = Path(args.source).resolve()
        if not source_path.is_dir() or not (source_path / 'config.json').is_file():
            raise SystemExit('Source folder is missing or does not contain config.json.')
        source = str(source_path)
    else:
        os.environ.pop('HF_HUB_OFFLINE', None)
        from huggingface_hub import snapshot_download
        print('Downloading original nezamisafa/whisper-persian-v4 weights (~6 GB).', flush=True)
        source = snapshot_download('nezamisafa/whisper-persian-v4',
            revision='b84fc89f5d8c6a08acbd0930c74010f8bb555253',
            local_dir=str(ROOT / 'models' / 'persian-v4-source'),
            allow_patterns=['*.json', '*.safetensors', '*.txt'], token=False)
    staging = ROOT / 'models' / 'persian-v4-converting'
    print('Converting locally; this requires several GB of free RAM.', flush=True)
    converter = TransformersConverter(source, copy_files=['preprocessor_config.json'], low_cpu_mem_usage=True, load_as_float16=True)
    converter.convert(str(staging), quantization='float16', force=True)
    AutoTokenizer.from_pretrained(source, local_files_only=True).backend_tokenizer.save(str(staging / 'tokenizer.json'))
    if not all((staging / f).exists() for f in ['model.bin','config.json','tokenizer.json']):
        raise RuntimeError('Conversion incomplete')
    staging.rename(target)
    print('Persian v4 ready. Choose Persian v4 in the app. Internet is no longer needed.')

if __name__ == '__main__':
    main()
