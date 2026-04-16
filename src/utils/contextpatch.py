import os
from re import sub
from difflib import SequenceMatcher
import logging
from pathlib import Path

from typing import Generator

class ContextPatcher:
    def __init__(self):
        self.logger = logging.getLogger("ContextPatcher")
        # Define fixed permissions for specific paths
        self.fix_permission = {
            "/vendor/bin/hw/android.hardware.wifi@1.0": ["u:object_r:hal_wifi_default_exec:s0"],
            "/system/system/app/*": ["u:object_r:system_file:s0"],
            "/system/system/priv-app/*": ["u:object_r:system_file:s0"],
            "/system/system/lib*": ["u:object_r:system_lib_file:s0"],
            "/system/system/bin/init": ["u:object_r:init_exec:s0"],
            "/system_ext/lib*": ["u:object_r:system_lib_file:s0"],
            "/product/lib*": ["u:object_r:system_lib_file:s0"],
            "/system/system/bin/app_process32": ["u:object_r:zygote_exec:s0"],
            "/system/system/bin/bootstrap/linker": ["u:object_r:system_linker_exec:s0"],
            "/system/system/bin/boringssl_self_test32": ["u:object_r:boringssl_self_test_exec:s0"],
            "/system/system/bin/drmserver": ["u:object_r:drmserver_exec:s0"],
            "/system/system/bin/linker": ["u:object_r:system_linker_exec:s0"],
            "/system/system/bin/mediaserver": ["u:object_r:mediaserver_exec:s0"],
            "/system_ext/bin/sigma_miracasthalservice": ["u:object_r:vendor_sigmahal_qti_exec:s0"],
            "/system_ext/bin/wfdservice": ["u:object_r:vendor_wfdservice_exec:s0"],
            "/my_product/vendor/etc/*.xml": ["u:object_r:vendor_configs_file:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.charger-V3-service": ["u:object_r:hal_charger_oplus_exec:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.charger-V6-service": ["u:object_r:hal_charger_oplus_exec:s0"],
            r"/odm/bin/hw/android\.hardware\.power\.stats-impl\.oplus": ["u:object_r:hal_power_stats_default_exec:s0"],
            r"/vendor/etc/permissions/android\.hardware\.hardware_keystore\.xml": ["u:object_r:vendor_configs_file:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.nfc_aidl-service": ["u:object_r:hal_oplus_nfc_default_exec:s0"],
            "/odm/bin/commcenterd": ["u:object_r:commcenterd_exec:s0"],
            "/odm/bin/hw/mdm_feature": ["u:object_r:mdm_feature_exec:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.wifi-aidl-service": ["u:object_r:oplus_wifi_aidl_service_exec:s0"],
            r"/odm/bin/hw/vendor-oplus-hardware-touch-V2-service": ["u:object_r:hal_oplus_touch_aidl_default_exec:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.eid@1\.0-service": ["u:object_r:hal_eid_oplus_exec:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.riskdetect-V1-service": ["u:object_r:hal_riskdetect_oplus_exec:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.urcc-service": ["u:object_r:hal_urcc_default_exec:s0"],
            "/odm/bin/hw/virtualcameraprovider": ["u:object_r:hal_virtualdevice_camera_exec:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.displaypanelfeature-service": ["u:object_r:oplus_hal_displaypanelfeature_exec:s0"],
            r"/odm/bin/hw/vendor\.oplus\.hardware\.engcamera@1\.0-service": ["u:object_r:engcamera_hidl_exec:s0"],
            r"/odm/bin/init\.oplus\.storage\.io_metrics\.sh": ["u:object_r:oplus_storage_io_metrics_exec:s0"],
            "/system_ext/xbin/xeu_toolbox": ["u:object_r:xeu_toolbox_exec:s0"],
            "*/etc/init/hw/*.rc": ["u:object_r:vendor_configs_file:s0"],
            r"/odm/lib/libmsnativefilter\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libmsnativefilter\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib/libextendfile\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libextendfile\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/android\.hardware\.graphics\.common-V5-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/android\.hardware\.common-V2-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/android\.hardware\.graphics\.common@1\.0\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/android\.hardware\.graphics\.allocator-V2-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/vendor\.qti\.hardware\.camera\.offlinecamera-V2-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/android\.hardware\.camera\.device-V2-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libAlgoInterface\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libAlgoProcess\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/android\.hardware\.common\.fmq-V1-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/android\.hardware\.camera\.metadata-V2-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/vendor\.oplus\.hardware\.osense\.client-V1-ndk\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/vendor/lib64/libc\+\+\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib/libNamaWrapper\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib/vendor\.oplus\.hardware\.sendextcamcmd-V1-service-impl\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib/libOplusSecurity\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libNamaWrapper\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib/libColorMark\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libColorMark\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libapsyuv\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libyuvwrapper\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/vendor\.oplus\.hardware\.sendextcamcmd-V1-service-impl\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libOplusSecurity\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib/libFilterWrapper\.so": ["u:object_r:same_process_hal_file:s0"],
            r"/odm/lib64/libFilterWrapper\.so": ["u:object_r:same_process_hal_file:s0"],
            "/odm/lib64/libaiboost*.so": ["u:object_r:same_process_hal_file:s0"],
            "/odm/lib64/aiframe/*.so": ["u:object_r:same_process_hal_file:s0"],
            "/odm/lib64/aiframe/cdsp/*signed/*.so": ["u:object_r:same_process_hal_file:s0"],
            "/system/system/bin/pif-updater": ["u:object_r:pif_updater_exec:s0"],
            "/odm/etc/camera/config/*": ["u:object_r:vendor_configs_file:s0"],
            r"/vendor/lib64/vendor\.oplus\.hardware\.sendextcamcmd-V1-ndk_platform\.so": ["u:object_r:same_process_hal_file:s0"],
            "/vendor/bin/qfp-daemon": ["u:object_r:vendor_qfp-daemon_exec:s0"],
            "/vendor/etc/init/*": ["u:object_r:vendor_configs_file:s0"],
            "/vendor/app/*": ["u:object_r:vendor_app_file:s0"],
        }

    def scan_context(self, file) -> dict:  
        """Read context file and return a dictionary"""
        context = {}
        try:
            with open(file, "r", encoding='utf-8') as file_:
                for line in file_:
                    # Filter empty lines and comments
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = line.replace('\\', '').split()
                    if not parts: 
                        continue
                        
                    filepath, *other = parts
                    context[filepath] = other
        except Exception as e:
            self.logger.error(f"Error scanning context file {file}: {e}")
        return context

    def scan_dir(self, folder) -> Generator[str, None, None]:  
        """Scan directory and yield paths formatted for context file"""
        folder_str = str(folder)
        part_name = os.path.basename(folder_str)
        
        # Hardcoded paths that might not be in the filesystem traversal
        allfiles = ['/', '/lost+found', f'/{part_name}/lost+found', f'/{part_name}', f'/{part_name}/']
        
        for root, dirs, files in os.walk(folder_str, topdown=True):
            for dir_ in dirs:
                # Format: /part_name/path/to/dir
                yield os.path.join(root, dir_).replace(folder_str, '/' + part_name).replace('\\', '/')
            for file in files:
                # Format: /part_name/path/to/file
                yield os.path.join(root, file).replace(folder_str, '/' + part_name).replace('\\', '/')
        
        for rv in allfiles:
            yield rv

    def context_patch(self, fs_file, dir_path) -> tuple:  
        """
        Compare filesystem against context file and patch missing entries.
        Returns: (new_fs_dict, added_count)
        """
        new_fs = {}
        # r_new_fs tracks newly added entries to prevent duplicates and for debugging
        r_new_fs = {} 
        add_new = 0
        permission_d = None
        dir_path_str = str(dir_path)
        
        self.logger.info(f"Loaded {len(fs_file)} entries from origin context.")
        
        # Determine default permission based on partition
        try:
            if dir_path_str.endswith('/system'):
                permission_d = ['u:object_r:system_file:s0']
            elif dir_path_str.endswith('/vendor'):
                permission_d = ['u:object_r:vendor_file:s0']
            else:
                # Fallback: try to pick an arbitrary permission from existing context
                if len(fs_file) > 5:
                    permission_d = fs_file.get(list(fs_file)[5])
        except Exception:
            pass
            
        if not permission_d:
            permission_d = ['u:object_r:system_file:s0']
            
        self.logger.debug(f"Default permission set to: {permission_d}")

        # Iterate through all files in the directory
        for i in self.scan_dir(os.path.abspath(dir_path_str)):
            # If entry exists in original context, keep it
            if fs_file.get(i):
                # Escape special characters for regex-like format in file_contexts
                safe_path = sub(r'([^-_/a-zA-Z0-9])', r'\\\1', i)
                new_fs[safe_path] = fs_file[i]
            else:
                # Entry missing, need to add it
                if r_new_fs.get(i):
                    continue # Already added
                
                permission = permission_d
                
                if i:
                    # 1. Check fixed permissions
                    if i in self.fix_permission:
                        permission = self.fix_permission[i]
                    else:
                        # 2. Fuzzy match: Find closest parent directory in existing context
                        parent_path = os.path.dirname(i)
                        
                        matched = False
                        # Optimization: Use keys iterator directly
                        for e in fs_file.keys():
                            # quick_ratio is faster for high volume comparisons
                            if SequenceMatcher(None, parent_path, e).quick_ratio() >= 0.85:
                                if e == parent_path: 
                                    continue
                                permission = fs_file[e]
                                matched = True
                                break
                        
                        if not matched:
                            permission = permission_d

                
                if i:
                    # 1. Check fixed permissions
                    if i in self.fix_permission:
                        permission = self.fix_permission[i]
                    else:
                        # 2. Fuzzy match: Find closest parent directory in existing context
                        parent_path = os.path.dirname(i)
                        
                        matched = False
                        # Optimization: Use keys iterator directly
                        for e in fs_file.keys():
                            # quick_ratio is faster for high volume comparisons
                            if SequenceMatcher(None, parent_path, e).quick_ratio() >= 0.85:
                                if e == parent_path: 
                                    continue
                                permission = fs_file[e]
                                matched = True
                                break
                        
                        if not matched:
                            permission = permission_d

                add_new += 1
                r_new_fs[i] = permission
                
                safe_path = sub(r'([^-_/a-zA-Z0-9])', r'\\\1', i)
                new_fs[safe_path] = permission
                
                # [DEBUG] Log the added entry
                self.logger.debug(f"[NEW ENTRY] {i} -> {permission}")

        return new_fs, add_new

    def patch(self, dir_path: Path, fs_config: Path) -> None:
        """Main entry point to patch a partition's file_contexts"""
        dir_path_str = str(dir_path)
        fs_config_str = str(fs_config)
        
        if not os.path.exists(dir_path_str) or not os.path.exists(fs_config_str):
            self.logger.warning(f"Path or config not found: {dir_path_str} | {fs_config_str}")
            return
            
        self.logger.info(f"Patching contexts for {os.path.basename(dir_path_str)}...")
        
        fs_file = self.scan_context(os.path.abspath(fs_config_str))
        new_fs, add_new = self.context_patch(fs_file, dir_path_str)
        
        # Write back to file
        try:
            with open(fs_config_str, "w", encoding='utf-8', newline='\n') as f:
                # Sort by path for consistency
                for path in sorted(new_fs.keys()):
                    line = f"{path} {' '.join(new_fs[path])}\n"
                    f.write(line)
                    
            self.logger.info(f"Context patch done. Added {add_new} new entries to {os.path.basename(fs_config_str)}.")
        except Exception as e:
            self.logger.error(f"Failed to write context file: {e}")
