import os
import shutil
import logging
import urllib.request
from pathlib import Path
from urllib.error import URLError

logger = logging.getLogger("AssetManager")

class AssetManager:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def ensure_asset(self, asset_path: Path) -> bool:
        """
        Ensures the asset at asset_path exists. 
        If not, attempts to download it from the base_url.
        """
        if asset_path.exists():
            return True

        filename = asset_path.name
        download_url = f"{self.base_url}/{filename}"
        
        logger.info(f"Asset missing: {asset_path}. Attempting download from {download_url}")
        
        try:
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Simple progress reporting could be added here if needed
            with urllib.request.urlopen(download_url, timeout=30) as response, open(asset_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            
            logger.info(f"Successfully downloaded {filename} to {asset_path}")
            return True
        except URLError as e:
            logger.error(f"Failed to download asset {filename} from {download_url}: {e}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred while downloading {filename}: {e}")
            return False
