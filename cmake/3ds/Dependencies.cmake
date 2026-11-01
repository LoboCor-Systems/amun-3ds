# Pinned source inputs for the 3GX build. devkitARM/libctru are supplied by the
# dated devkitPro image or its 3ds-dev pacman group; proprietary SDK material is not used.
set(AMUN_LUMA_REFERENCE_VERSION "13.4")
set(AMUN_DEVKITARM_REFERENCE_RELEASE "68")
set(AMUN_LIBCTRU_REFERENCE_VERSION "2.7.0")
set(AMUN_DEVKITPRO_IMAGE_TAG "devkitpro/devkitarm:20260610")
set(AMUN_DEVKITPRO_IMAGE_DIGEST
    "sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5")
set(AMUN_DEVKITPRO_IMAGE
    "devkitpro/devkitarm@${AMUN_DEVKITPRO_IMAGE_DIGEST}")

set(AMUN_CTRPF_REPOSITORY
    "https://gitlab.com/thepixellizeross/ctrpluginframework.git")
set(AMUN_CTRPF_REVISION
    "6671936663faaa900f7cfdeedf42bc8581560f4f")

set(AMUN_3GXTOOL_REPOSITORY
    "https://gitlab.com/thepixellizeross/3gxtool.git")
set(AMUN_3GXTOOL_REVISION
    "57e3160ab72d8533a2f0601efdc8a149b4825ea5")
