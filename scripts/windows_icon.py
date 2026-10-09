"""为未签名的 Windows 安装器写入多尺寸 ICO，并核对嵌入资源。"""
import ctypes
from ctypes import wintypes
import struct


def icon_images(path):
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', data)
    if reserved or kind != 1 or not count:
        raise ValueError('图标文件格式无效。')
    entries, images = [], []
    for index in range(count):
        width, height, colors, unused, planes, bits, size, offset = struct.unpack_from('<BBBBHHII', data, 6 + index * 16)
        image = data[offset:offset + size]
        if len(image) != size:
            raise ValueError('图标文件不完整。')
        entries.append(struct.pack('<BBBBHHIH', width, height, colors, unused, planes, bits, size, 2000 + index))
        images.append(image)
    return struct.pack('<HHH', 0, 1, count) + b''.join(entries), images


def kernel():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD]
    api.LoadLibraryExW.restype = ctypes.c_void_p
    api.FreeLibrary.argtypes = [ctypes.c_void_p]
    api.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    api.BeginUpdateResourceW.restype = ctypes.c_void_p
    api.UpdateResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    api.EndUpdateResourceW.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    api.FindResourceExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD]
    api.FindResourceExW.restype = ctypes.c_void_p
    api.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    api.LoadResource.restype = ctypes.c_void_p
    api.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    api.LockResource.argtypes = [ctypes.c_void_p]
    api.LockResource.restype = ctypes.c_void_p
    return api


def pointer(name):
    return ctypes.c_void_p(name) if isinstance(name, int) else ctypes.cast(ctypes.c_wchar_p(name), ctypes.c_void_p)


def groups(api, module):
    result = []
    name_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)
    language_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_ssize_t)
    api.EnumResourceNamesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, name_callback, ctypes.c_ssize_t]
    api.EnumResourceLanguagesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, language_callback, ctypes.c_ssize_t]

    @name_callback
    def on_name(handle, kind, name, parameter):
        value = name if name <= 65535 else ctypes.wstring_at(name)

        @language_callback
        def on_language(handle, kind, name, language, parameter):
            result.append((value, language))
            return True

        api.EnumResourceLanguagesW(module, 14, pointer(value), on_language, 0)
        return True

    api.EnumResourceNamesW(module, 14, on_name, 0)
    return result


def resource_bytes(api, module, kind, name, language):
    found = api.FindResourceExW(module, pointer(kind), pointer(name), language)
    if not found:
        raise ctypes.WinError(ctypes.get_last_error())
    size = api.SizeofResource(module, found)
    address = api.LockResource(api.LoadResource(module, found))
    return ctypes.string_at(address, size)


def verify_executable_icon(executable, icon):
    expected, images = icon_images(icon)
    api = kernel()
    module = api.LoadLibraryExW(str(executable), None, 2)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        targets = groups(api, module)
        assert targets, '安装器缺少图标组。'
        for name, language in targets:
            assert resource_bytes(api, module, 14, name, language) == expected, '安装器图标组与品牌图标不一致。'
            for index, image in enumerate(images):
                assert resource_bytes(api, module, 3, 2000 + index, language) == image, '安装器图标像素资源不一致。'
    finally:
        api.FreeLibrary(module)


def replace_executable_icon(executable, icon):
    group, images = icon_images(icon)
    original = executable.read_bytes()
    cabinet_offset = original.rfind(b'MSCF')
    if cabinet_offset < 0:
        raise ValueError('安装器缺少 CAB 负载。')
    cabinet_size = struct.unpack_from('<I', original, cabinet_offset + 8)[0]
    cabinet = original[cabinet_offset:cabinet_offset + cabinet_size]
    api = kernel()
    module = api.LoadLibraryExW(str(executable), None, 2)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        targets = groups(api, module) or [(1, 1033)]
    finally:
        api.FreeLibrary(module)
    update = api.BeginUpdateResourceW(str(executable), False)
    if not update:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        def write(kind, name, language, data):
            buffer = ctypes.create_string_buffer(data)
            if not api.UpdateResourceW(update, pointer(kind), pointer(name), language, buffer, len(data)):
                raise ctypes.WinError(ctypes.get_last_error())

        for language in {language for _, language in targets}:
            for index, image in enumerate(images):
                write(3, 2000 + index, language, image)
        for name, language in targets:
            write(14, name, language, group)
    except BaseException:
        api.EndUpdateResourceW(update, True)
        raise
    if not api.EndUpdateResourceW(update, False):
        raise ctypes.WinError(ctypes.get_last_error())
    # 安装器 CAB 必须完整保留；不接受只更换外观却破坏安装负载的产物。
    assert cabinet in executable.read_bytes(), '写入图标后 CAB 负载不完整，请重新构建安装器。'
    verify_executable_icon(executable, icon)
