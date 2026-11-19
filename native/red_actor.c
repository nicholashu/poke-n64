#include "poke_red.h"
#include "poke_oot.h"
#include "player.h"
#include "save.h"
#include "gfx_setupdl.h"

void PokeRed_HideLinkLimb(PlayState* play,Gfx** dList) {
    static Gfx empty[] = { gsSPEndDisplayList() };
    /* Preserve the original null/non-null limb structure and post-limb
     * callbacks. Native body-part indexing, feet and focus still update. */
    if (PokeOot_IsScene(play->sceneId) && !LINK_IS_ADULT && *dList!=NULL)
        *dList=empty;
}
void PokeRed_Setup(GraphicsContext* gfx) {
    Gfx_SetupDL_25Opa(gfx);
    OPEN_DISPS(gfx);
    gDPPipeSync(POLY_OPA_DISP++);
    gSPClearGeometryMode(POLY_OPA_DISP++,G_LIGHTING|G_TEXTURE_GEN|G_TEXTURE_GEN_LINEAR|G_CULL_FRONT|G_CULL_BACK);
    gSPSetGeometryMode(POLY_OPA_DISP++,G_SHADE|G_ZBUFFER);
    gSPTexture(POLY_OPA_DISP++,0,0,0,G_TX_RENDERTILE,G_OFF);
    gDPSetCycleType(POLY_OPA_DISP++,G_CYC_1CYCLE);
    gDPSetCombineMode(POLY_OPA_DISP++,G_CC_SHADE,G_CC_SHADE);
    gDPSetRenderMode(POLY_OPA_DISP++,G_RM_AA_ZB_OPA_SURF,G_RM_AA_ZB_OPA_SURF2);
    CLOSE_DISPS(gfx);
}
