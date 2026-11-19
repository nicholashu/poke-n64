/* Native Pokémon opening: real OoT player physics, scene loads and camera.
 * Story state survives PlayState replacement; cartridge persistence is separate.
 */
#include "poke_oot.h"
#include "poke_intro.h"
#include "poke_world_native.h"
#include "poke_red.h"
#include "player.h"
#include "controller.h"
#include "gfx.h"
#include "libu64/gfxprint.h"
#include "save.h"
#include "stadium_asset.h"
#include "sys_matrix.h"
#include "sys_math.h"
#include "z_lib.h"
#include "view.h"
#include "poke_pallet_native.h"

typedef struct {
    PokeGame game;
    PokeIntro intro;
    Vec3f previous, battleAnchor, oakPosition;
    f32 phase, gait, distanceSinceStep;
    u32 frame;
    s16 battleCameraId, fieldCameraId;
    u16 previousTurns;
    u8 initialized, havePrevious, attackFrames, telemetry, wakeFrames;
} PokeOotRuntime;
static PokeOotRuntime sPokeOot;

static s32 room_for_scene(s32 scene) {
    s32 i;
    for (i=0;i<INTRO_ROOM_COUNT;++i) if (sPokeSceneIds[i]==scene) return i;
    return -1;
}
/* A supplied Red/Blue ROM replaces Pallet Town's scene geometry and text
 * data. It must not replace the five-room opening/story with the earlier
 * isolated outdoor demo. That event runner remains available for tools. */
s32 PokeOot_ImportedPallet(void) { return 0; }
s32 PokeOot_IsScene(s32 scene) {
    return PokeOot_ImportedPallet() ? scene==SCENE_KOKIRI_FOREST : room_for_scene(scene)>=0;
}
s32 PokeOot_BattleActive(void) { return sPokeOot.initialized && poke_in_battle(&sPokeOot.game); }
s32 PokeOot_InputLocked(void) {
    if (PokeOot_ImportedPallet()) return !sPokeOot.initialized || PokePalletNative_InputLocked();
    return !sPokeOot.initialized || PokeOot_BattleActive() ||
           poke_intro_locked(&sPokeOot.intro) || sPokeOot.wakeFrames;
}
s32 PokeOot_ResolveSpawn(s32 sceneId,s32 original) {
    PokeIntro* s=&sPokeOot.intro;
    if (PokeOot_ImportedPallet()) return original;
    if (sPokeOot.initialized && s->warp_pending &&
        sPokeSceneIds[s->warp_room]==sceneId) return s->warp_spawn;
    return original;
}
static f32 cell_x(s32 room,f32 x) { return (x+.5f-gPokeIntroMaps[room].width*.5f)*POKE_WORLD_CELL; }
static f32 cell_z(s32 room,f32 z) { return (z+.5f-gPokeIntroMaps[room].height*.5f)*POKE_WORLD_CELL; }
static s32 tile_x(s32 room,f32 x) { return (s32)((x+gPokeIntroMaps[room].width*POKE_WORLD_CELL*.5f)/POKE_WORLD_CELL); }
static s32 tile_z(s32 room,f32 z) { return (s32)((z+gPokeIntroMaps[room].height*POKE_WORLD_CELL*.5f)/POKE_WORLD_CELL); }
static f32 clamp(f32 x,f32 low,f32 high) { return x<low ? low : x>high ? high : x; }

/* D-pad directions are world cardinal directions, converted to native analog
 * input. The ordinary analog stick remains camera-relative. Both paths use
 * OoT's Player_Update, acceleration and scene collision, never a test teleport. */
void PokeOot_PrepareInput(PlayState* play) {
    Input* in=&play->state.input[0];
    u16 buttons=in->cur.button;
    s16 target=0,delta;
    if (!PokeOot_IsScene(play->sceneId)) return;
    if (GET_PLAYER(play)) GET_PLAYER(play)->naviTextId=0;
    if (PokeOot_InputLocked()) {
        in->cur.button=in->press.button=in->rel.button=0;
        in->cur.stick_x=in->cur.stick_y=in->rel.stick_x=in->rel.stick_y=0;
        if (GET_PLAYER(play)!=NULL) { GET_PLAYER(play)->speedXZ=0; GET_PLAYER(play)->actor.speed=0; }
        return;
    }
    if (buttons&(BTN_DUP|BTN_DDOWN|BTN_DLEFT|BTN_DRIGHT)) {
        if (buttons&BTN_DUP) target=(s16)0x8000;
        else if (buttons&BTN_DDOWN) target=0;
        else if (buttons&BTN_DLEFT) target=(s16)0xC000;
        else target=0x4000;
        delta=target-Camera_GetInputDirYaw(GET_ACTIVE_CAM(play));
        in->rel.stick_x=(s8)(-Math_SinS(delta)*45.0f);
        in->rel.stick_y=(s8)(Math_CosS(delta)*45.0f);
        in->cur.stick_x=in->rel.stick_x; in->cur.stick_y=in->rel.stick_y;
    }
    /* A/B belong to interaction and battle, not Zelda rolls/weapons. */
    in->cur.button&=~(BTN_A|BTN_B|BTN_START|BTN_L|BTN_R|BTN_CLEFT|BTN_CRIGHT|BTN_CUP|BTN_CDOWN);
    in->press.button&=~(BTN_A|BTN_B|BTN_START|BTN_L|BTN_R|BTN_CLEFT|BTN_CRIGHT|BTN_CUP|BTN_CDOWN);
    in->rel.button&=~(BTN_A|BTN_B|BTN_START|BTN_L|BTN_R|BTN_CLEFT|BTN_CRIGHT|BTN_CUP|BTN_CDOWN);
}

/* Keep OoT's main chase camera active in every Pokemon room.
 * The previous custom subcamera forced eye.y=player.y+550, creating
 * the top-down viewpoint the game is not intended to use. A battle
 * temporarily switches to its own subcamera, then restores CAM_ID_MAIN. */
static void silent_navi(Actor* actor,PlayState* play) {
    (void)actor; (void)play;
}
static void suppress_navi(PlayState* play) {
    Player* player=GET_PLAYER(play);
    Actor* navi;
    if (!player) return;
    player->naviTextId=0;
    navi=player->naviActor;
    /* Player and message code retain this pointer. Keep the initialized
     * allocation and its original destructor, but never run fairy behavior.
     * EnElf_Init leaves both lights at radius zero; updates would enable them. */
    if (navi && navi->init==NULL) {
        navi->update=silent_navi; navi->draw=NULL; navi->sfx=0; navi->textId=0;
    }
}
void PokeOot_OnSceneEnter(PlayState* play) {
    s32 room=room_for_scene(play->sceneId);
    if (room<0) return;
    suppress_navi(play);
    if (PokeOot_ImportedPallet()) {
        if (play->sceneId!=SCENE_KOKIRI_FOREST) return;
        if (!sPokeOot.initialized) {
            poke_init(&sPokeOot.game,(u32)osGetTime()^0x504F4B45U);
            sPokeOot.initialized=1;
        }
        sPokeOot.havePrevious=0; sPokeOot.gait=0;
        sPokeOot.battleCameraId=CAM_ID_NONE; sPokeOot.fieldCameraId=CAM_ID_NONE;
        PokePalletNative_OnSceneEnter(play);
        return;
    }
    if (!sPokeOot.initialized) {
        poke_init(&sPokeOot.game,(u32)osGetTime()^0x504F4B45U);
        poke_intro_init(&sPokeOot.intro);
        sPokeOot.initialized=1;
    }
    poke_intro_enter(&sPokeOot.intro,(u8)room);
    sPokeOot.havePrevious=0; sPokeOot.gait=0;
    sPokeOot.battleCameraId=CAM_ID_NONE; sPokeOot.fieldCameraId=CAM_ID_NONE;
    /* All five rooms now use OoT's normal main chase camera. */
}
static u16 battle_input(const Input* in) {
    u16 keys=0;
    if (in->cur.button&BTN_A) keys|=KEY_A;
    if (in->cur.button&BTN_B) keys|=KEY_B;
    if ((in->cur.button&BTN_DUP) || in->cur.stick_y>24) keys|=KEY_UP;
    if ((in->cur.button&BTN_DDOWN) || in->cur.stick_y< -24) keys|=KEY_DOWN;
    return keys;
}
static void start_battle_camera(PlayState* play) {
    Vec3f at,eye;
    s16 id=Play_CreateSubCamera(play);
    sPokeOot.battleCameraId=id;
    sPokeOot.battleAnchor.x=cell_x(sPokeOot.intro.room,sPokeOot.intro.room==INTRO_LAB ? 4.5f : 8.0f);
    sPokeOot.battleAnchor.y=0;
    sPokeOot.battleAnchor.z=cell_z(sPokeOot.intro.room,sPokeOot.intro.room==INTRO_LAB ? 9.0f : 7.0f);
    sPokeOot.previousTurns=0; sPokeOot.attackFrames=0;
    if (id==CAM_ID_NONE) return;
    at=sPokeOot.battleAnchor; at.y+=55;
    eye=at; eye.x+=140; eye.y+=230; eye.z+=470;
    Play_ChangeCameraStatus(play,sPokeOot.fieldCameraId==CAM_ID_NONE ? CAM_ID_MAIN : sPokeOot.fieldCameraId,CAM_STAT_WAIT);
    Play_ChangeCameraStatus(play,id,CAM_STAT_ACTIVE);
    Play_SetCameraAtEye(play,id,&at,&eye); Play_SetCameraFov(play,id,48);
}
static void stop_battle_camera(PlayState* play) {
    s16 id=sPokeOot.battleCameraId;
    if (id!=CAM_ID_NONE) {
        Play_ClearCamera(play,id);
        Play_ChangeCameraStatus(play,sPokeOot.fieldCameraId==CAM_ID_NONE ? CAM_ID_MAIN : sPokeOot.fieldCameraId,CAM_STAT_ACTIVE);
    }
    sPokeOot.battleCameraId=CAM_ID_NONE; sPokeOot.attackFrames=0;
}
static void request_warp(PlayState* play) {
    PokeIntro* s=&sPokeOot.intro;
    if (!s->warp_pending || play->transitionTrigger!=TRANS_TRIGGER_OFF || play->transitionMode!=TRANS_MODE_OFF) return;
    play->nextEntranceIndex=sPokeEntrances[s->warp_room];
    play->transitionType=TRANS_TYPE_FADE_BLACK_FAST;
    gSaveContext.nextTransitionType=TRANS_TYPE_FADE_BLACK_FAST;
    play->transitionTrigger=TRANS_TRIGGER_START;
}
static void escort(PlayState* play,Player* player) {
    int tx,tz;
    f32 x,z,dx,dz,length,step=3.2f;
    (void)play;
    if (!poke_intro_escort_target(&sPokeOot.intro,&tx,&tz)) return;
    x=cell_x(INTRO_PALLET,(f32)tx); z=cell_z(INTRO_PALLET,(f32)tz);
    dx=x-player->actor.world.pos.x; dz=z-player->actor.world.pos.z;
    length=sqrtf(dx*dx+dz*dz);
    if (length<step) {
        player->actor.world.pos.x=x; player->actor.world.pos.z=z;
        poke_intro_escort_arrived(&sPokeOot.intro);
    } else {
        player->actor.world.pos.x+=dx/length*step;
        player->actor.world.pos.z+=dz/length*step;
        player->actor.shape.rot.y=Math_Atan2S(dz,dx);
        player->actor.world.rot.y=player->actor.shape.rot.y;
    }
    /* Oak leads the player toward the next waypoint, with a bounded gap. */
    sPokeOot.oakPosition=player->actor.world.pos;
    if (length>1) {
        sPokeOot.oakPosition.x+=dx/length*40;
        sPokeOot.oakPosition.z+=dz/length*40;
    }
}
static void npc_collision(Player* p,s32 x,s32 z) {
    f32 dx=p->actor.world.pos.x-cell_x(sPokeOot.intro.room,(f32)x);
    f32 dz=p->actor.world.pos.z-cell_z(sPokeOot.intro.room,(f32)z);
    if (dx*dx+dz*dz<52*52 && sPokeOot.havePrevious) {
        p->actor.world.pos.x=sPokeOot.previous.x;
        p->actor.world.pos.z=sPokeOot.previous.z;
        p->speedXZ=0; p->actor.speed=0;
    }
}
static void block_npcs(Player* p) {
    PokeIntro* s=&sPokeOot.intro;
    if (s->stage==INTRO_ESCORT) return;
    if (s->room==INTRO_HOME) npc_collision(p,5,4);
    else if (s->room==INTRO_BLUE_HOUSE) npc_collision(p,2,3);
    else if (s->room==INTRO_PALLET) { npc_collision(p,3,8); npc_collision(p,11,14); }
    else if (s->room==INTRO_LAB) {
        npc_collision(p,1,9); npc_collision(p,2,10); npc_collision(p,8,10);
        if (s->stage>=INTRO_CHOOSE) npc_collision(p,5,2);
        if (s->stage<INTRO_COMPLETE) npc_collision(p,4,3);
    }
}
void PokeOot_Update(PlayState* play) {
    Player* p=GET_PLAYER(play);
    Input* in=&play->state.input[0];
    PokeIntro* s=&sPokeOot.intro;
    f32 dx,dz,travelled;
    s32 x,z;
    u8 before;
    u16 pressed=0;
    if (!sPokeOot.initialized || !p || !PokeOot_IsScene(play->sceneId)) return;
    if (PokeOot_ImportedPallet()) {
        ++sPokeOot.frame;
        if (play->transitionTrigger!=TRANS_TRIGGER_OFF || play->transitionMode!=TRANS_MODE_OFF) return;
        PokePalletNative_Update(play);
        /* Red uses the same original walking mesh in both modes. Imported
         * actor placement/story remains independent of the authored opening. */
        sPokeOot.gait=0;
        if (sPokeOot.havePrevious) {
            dx=p->actor.world.pos.x-sPokeOot.previous.x;
            dz=p->actor.world.pos.z-sPokeOot.previous.z;
            travelled=sqrtf(dx*dx+dz*dz);
            if (travelled<40) {
                sPokeOot.phase+=travelled*.14f;
                if (sPokeOot.phase>6.2831853f) sPokeOot.phase-=6.2831853f;
                sPokeOot.gait=clamp(travelled/3.0f,0,1);
            }
        }
        sPokeOot.previous=p->actor.world.pos; sPokeOot.havePrevious=1;
        return;
    }
    ++sPokeOot.frame;
    if (sPokeOot.attackFrames) --sPokeOot.attackFrames;
    if (sPokeOot.wakeFrames) --sPokeOot.wakeFrames;
    if ((in->cur.button&(BTN_L|BTN_R|BTN_Z))==(BTN_L|BTN_R|BTN_Z) && (in->press.button&BTN_START))
        sPokeOot.telemetry^=1;
    if (play->transitionTrigger!=TRANS_TRIGGER_OFF || play->transitionMode!=TRANS_MODE_OFF) return;
    if (in->press.button&BTN_A) pressed|=KEY_A;
    if (in->press.button&BTN_B) pressed|=KEY_B;
    before=s->stage;
    if (PokeOot_BattleActive()) {
        u16 keys=battle_input(in);
        if (sPokeOot.battleCameraId==CAM_ID_NONE) start_battle_camera(play);
        poke_update(&sPokeOot.game,keys);
        if (sPokeOot.game.turns!=sPokeOot.previousTurns) {
            sPokeOot.previousTurns=sPokeOot.game.turns; sPokeOot.attackFrames=18;
        }
        if (PokeOot_BattleActive()) return;
        stop_battle_camera(play);
    }
    block_npcs(p);
    x=tile_x(s->room,p->actor.world.pos.x); z=tile_z(s->room,p->actor.world.pos.z);
    dx=Math_SinS(p->actor.shape.rot.y); dz=Math_CosS(p->actor.shape.rot.y);
    if (dx*dx>dz*dz) poke_intro_face(s,dx<0 ? -1 : 1,0);
    else poke_intro_face(s,0,dz<0 ? -1 : 1);
    if (!sPokeOot.wakeFrames) poke_intro_update(s,&sPokeOot.game,x,z,pressed);
    if (before==INTRO_WAKE && s->stage!=INTRO_WAKE) sPokeOot.wakeFrames=20;
    if (s->reposition) {
        p->actor.world.pos.x=cell_x(s->room,s->reposition_x);
        p->actor.world.pos.z=cell_z(s->room,s->reposition_z);
        p->actor.prevPos=p->actor.world.pos;
        s->reposition=0; sPokeOot.havePrevious=0;
    }
    if (s->stage==INTRO_ESCORT) escort(play,p);
    if (PokeOot_BattleActive()) start_battle_camera(play);
    /* Preserve the previous debug battle shortcut only after completing the
     * opening. It cannot skip starter selection or the first rival fight. */
    if (s->stage==INTRO_COMPLETE && s->talk==TALK_NONE &&
        (in->cur.button&(BTN_L|BTN_R))==(BTN_L|BTN_R) && (in->press.button&BTN_B)) {
        if (poke_start_encounter(&sPokeOot.game,POKE_RATTATA,4)==POKE_OK) start_battle_camera(play);
    }
    if (sPokeOot.havePrevious) {
        dx=p->actor.world.pos.x-sPokeOot.previous.x;
        dz=p->actor.world.pos.z-sPokeOot.previous.z;
        travelled=sqrtf(dx*dx+dz*dz);
        if (travelled<40) {
            sPokeOot.phase+=travelled*.14f;
            if (sPokeOot.phase>6.2831853f) sPokeOot.phase-=6.2831853f;
            sPokeOot.gait=clamp(travelled/3.0f,0,1);
            sPokeOot.distanceSinceStep+=travelled;
            if (sPokeOot.distanceSinceStep>=POKE_WORLD_CELL) {
                sPokeOot.distanceSinceStep-=POKE_WORLD_CELL; ++sPokeOot.game.steps;
            }
        } else sPokeOot.gait=0;
    }
    sPokeOot.previous=p->actor.world.pos; sPokeOot.havePrevious=1;
    request_warp(play);
}

/* Prefer original dialogue extracted locally from the user-supplied
 * Game Boy ROM for outdoor signs, residents and Oak's grass warning.
 * The portable story remains responsible for Oak's escort and transitions.
 * Only a 2x36-character view is exposed to the native GfxPrint UI. */
static const char* intro_line( const PokeIntro* intro, const PokeGame* game, unsigned line) {
    static char wrapped[2][37];
    const char* source;
    s32 textId=POKE_PALLET_TEXT_NONE;
    unsigned index=0, row=0, column=0;
    if (line>1 || intro->room!=INTRO_PALLET || !gPokePalletMap.enabled ||
        gPokePalletMap.texts==NULL) return poke_intro_line(intro,game,line);
    switch (intro->talk) {
        case TALK_OAK_WARNING: textId=POKE_PALLET_TEXT_OAK_UNSAFE; break;
        case TALK_GIRL: textId=POKE_PALLET_TEXT_GIRL; break;
        case TALK_FISHER: textId=POKE_PALLET_TEXT_FISHER; break;
        case TALK_RED_SIGN: textId=POKE_PALLET_TEXT_PLAYER_HOUSE_SIGN; break;
        case TALK_BLUE_SIGN: textId=POKE_PALLET_TEXT_RIVAL_HOUSE_SIGN; break;
        case TALK_TOWN_SIGN: textId=POKE_PALLET_TEXT_TOWN_SIGN; break;
        case TALK_LAB_SIGN: textId=POKE_PALLET_TEXT_LAB_SIGN; break;
        default: break;
    }
    if (textId==POKE_PALLET_TEXT_NONE) return poke_intro_line(intro,game,line);
    source=gPokePalletMap.texts[textId];
    if (source==NULL || source[0]=='\0') return poke_intro_line(intro,game,line);
    wrapped[0][0]=wrapped[1][0]='\0';
    /* Stable, bounded output: support original line endings and wrap after
     * 36 characters without overrunning the N64 framebuffer text box. */
    while (source[index]!='\0' && index<POKE_PALLET_TEXT_LIMIT && row<2) {
        char ch=source[index++];
        if (ch=='\r') continue;
        if (ch=='\n' || column==36) {
            wrapped[row][column]='\0';
            ++row;column=0;
            if (row>=2) break;
            if (ch=='\n') continue;
        }
        wrapped[row][column++]=ch;
    }
    if (row<2) wrapped[row][column]='\0';
    return wrapped[line];
}

static void human(PlayState* play,s32 kind,f32 x,f32 y,f32 z,s16 yaw,f32 gait) {
    GraphicsContext* gfx=play->state.gfxCtx;
    Matrix_Push(); Matrix_Translate(x,y,z,MTXMODE_NEW);
    Matrix_RotateY(BINANG_TO_RAD(yaw),MTXMODE_APPLY);
    if (kind==MODEL_OAK || kind==MODEL_SCIENTIST) Matrix_Scale(1.12f,1.12f,1.12f,MTXMODE_APPLY);
    PokeRed_Setup(gfx);
    PokeModels_DrawHuman(gfx,kind,sPokeOot.phase,gait);
    Matrix_Pop();
}
static void npc(PlayState* play,s32 kind,s32 x,s32 z,s16 yaw) {
    human(play,kind,cell_x(sPokeOot.intro.room,(f32)x),0,cell_z(sPokeOot.intro.room,(f32)z),yaw,0);
}
static void ball(PlayState* play,s32 x) {
    GraphicsContext* gfx=play->state.gfxCtx;
    /* Small original two-tone geometric Poké Ball, independent of ROM assets. */
    static Vtx vertices[] = {
        {{{-9,0,0},0,{0,0},{216,53,48,255}}}, {{{0,9,0},0,{0,0},{244,75,67,255}}},
        {{{9,0,0},0,{0,0},{216,53,48,255}}}, {{{0,0,9},0,{0,0},{225,65,56,255}}},
        {{{0,0,-9},0,{0,0},{216,53,48,255}}}, {{{0,-9,0},0,{0,0},{238,233,211,255}}}
    };
    Matrix_Push(); Matrix_Translate(cell_x(INTRO_LAB,(f32)x),58,cell_z(INTRO_LAB,3),MTXMODE_NEW);
    PokeRed_Setup(gfx);
    OPEN_DISPS(gfx);
    MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++,gfx);
    gSPVertex(POLY_OPA_DISP++,vertices,6,0);
    gSP2Triangles(POLY_OPA_DISP++,0,1,3,0,3,1,2,0);
    gSP2Triangles(POLY_OPA_DISP++,2,1,4,0,4,1,0,0);
    gSP2Triangles(POLY_OPA_DISP++,0,3,5,0,3,2,5,0);
    gSP2Triangles(POLY_OPA_DISP++,2,4,5,0,4,0,5,0);
    CLOSE_DISPS(gfx); Matrix_Pop();
}
static void draw_world_people(PlayState* play,Player* p) {
    PokeIntro* s=&sPokeOot.intro;
    f32 t;
    if (s->stage==INTRO_WAKE || sPokeOot.wakeFrames) {
        t=s->stage==INTRO_WAKE ? 0 : 1-sPokeOot.wakeFrames/20.0f;
        Matrix_Push();
        Matrix_Translate(cell_x(INTRO_BEDROOM,0)+t*80,30*(1-t),cell_z(INTRO_BEDROOM,6.625f)-t*50,MTXMODE_NEW);
        Matrix_RotateX(-(1-t)*1.5707963f,MTXMODE_APPLY);
        Matrix_RotateY(t*3.14159265f,MTXMODE_APPLY);
        PokeRed_Setup(play->state.gfxCtx);
        PokeModels_DrawHuman(play->state.gfxCtx,MODEL_RED,0,0);
        Matrix_Pop();
    } else human(play,MODEL_RED,p->actor.world.pos.x,p->actor.world.pos.y,p->actor.world.pos.z,p->actor.shape.rot.y,sPokeOot.gait);
    if (s->room==INTRO_HOME) npc(play,MODEL_MOM,5,4,(s16)0xC000);
    else if (s->room==INTRO_BLUE_HOUSE) npc(play,MODEL_DAISY,2,3,0x4000);
    else if (s->room==INTRO_PALLET) {
        npc(play,MODEL_GIRL,3,8,0); npc(play,MODEL_FISHER,11,14,0);
        if (s->stage==INTRO_OAK_WARNING) {
            human(play,MODEL_OAK,p->actor.world.pos.x,0,p->actor.world.pos.z+80,(s16)0x8000,0);
        } else if (s->stage==INTRO_ESCORT)
            human(play,MODEL_OAK,sPokeOot.oakPosition.x,0,sPokeOot.oakPosition.z,p->actor.shape.rot.y,1);
    } else if (s->room==INTRO_LAB) {
        s32 i; static const u8 choices[]={POKE_CHARMANDER,POKE_SQUIRTLE,POKE_BULBASAUR};
        if (s->stage>=INTRO_LAB_WELCOME) npc(play,MODEL_OAK,5,2,0);
        if (s->stage<INTRO_COMPLETE) npc(play,MODEL_BLUE,4,3,0);
        npc(play,MODEL_GIRL,1,9,0); npc(play,MODEL_SCIENTIST,2,10,0); npc(play,MODEL_SCIENTIST,8,10,0);
        for (i=0;i<3;++i) if (choices[i]!=s->starter && choices[i]!=s->rival) ball(play,6+i);
    }
}
static void pokemon(PlayState* play,s32 species,f32 x,f32 z,s16 yaw) {
    GraphicsContext* gfx=play->state.gfxCtx;
    Matrix_Push(); Matrix_Translate(x,0,z,MTXMODE_NEW); Matrix_RotateY(BINANG_TO_RAD(yaw),MTXMODE_APPLY);
    if (species==POKE_BULBASAUR && PokeStadium_AssetAvailable()) {
        OPEN_DISPS(gfx); MATRIX_FINALIZE_AND_LOAD(POLY_OPA_DISP++,gfx); CLOSE_DISPS(gfx);
        PokeStadium_DrawBulbasaur(gfx,sPokeOot.attackFrames!=0,sPokeOot.frame);
    } else { PokeRed_Setup(gfx); PokeModels_DrawPokemon(gfx,species); }
    Matrix_Pop();
}
static void draw_battle(PlayState* play) {
    Vec3f at=sPokeOot.battleAnchor;
    PokeGame* g=&sPokeOot.game;
    f32 lunge=sPokeOot.attackFrames ? Math_SinF(sPokeOot.attackFrames*.1745329f)*12 : 0;
    human(play,MODEL_RED,at.x-125,0,at.z+160,(s16)0x8000,0);
    if (g->trainer_battle) human(play,MODEL_BLUE,at.x+105,0,at.z-155,0,0);
    pokemon(play,g->party[g->active].species,at.x-65,at.z+70-lunge,(s16)0x8000);
    pokemon(play,g->enemy.species,at.x+65,at.z-70,0);
}
static void panel(GraphicsContext* gfx,s32 x,s32 y,s32 w,s32 h) {
    u32 color=GPACK_RGBA5551(21,37,47,1);
    OPEN_DISPS(gfx); gDPPipeSync(OVERLAY_DISP++); gDPSetCycleType(OVERLAY_DISP++,G_CYC_FILL);
    gDPSetRenderMode(OVERLAY_DISP++,G_RM_NOOP,G_RM_NOOP2);
    gDPSetFillColor(OVERLAY_DISP++,(color<<16)|color);
    gDPFillRectangle(OVERLAY_DISP++,x,y,x+w-1,y+h-1); gDPPipeSync(OVERLAY_DISP++); CLOSE_DISPS(gfx);
}

/* Read-only, opt-in 32-byte visual telemetry. No memory writes, test commands,
 * RNG overrides or story shortcuts. CRC + frame let scripts reject stale or
 * unreadable captures. Toggle L+R+Z+START; absent from normal gameplay. */
static void telemetry(PlayState* play,Player* p) {
    u8 data[32]={0}; u32 crc; s32 i,x,y,facing; u16 px,pz;
    PokeIntro* s=&sPokeOot.intro; PokeGame* g=&sPokeOot.game;
    GraphicsContext* gfx=play->state.gfxCtx;
    if (!sPokeOot.telemetry) return;
    data[0]='P';data[1]='K';data[2]='6';data[3]='4';data[4]=1;
    data[5]=s->room;data[6]=s->stage;data[7]=s->talk;
    data[8]=s->starter;data[9]=s->rival;data[10]=g->mode;data[11]=g->battle_result;
    data[12]=g->party_count ? (u8)g->party[g->active].hp : 0; data[13]=(u8)g->enemy.hp;
    data[14]=g->party_count ? (u8)g->party[g->active].max_hp : 0;data[15]=(u8)g->enemy.max_hp;
    px=(u16)clamp((p->actor.world.pos.x+gPokeIntroMaps[s->room].width*40)*4,0,65535);
    pz=(u16)clamp((p->actor.world.pos.z+gPokeIntroMaps[s->room].height*40)*4,0,65535);
    data[16]=px>>8;data[17]=px;data[18]=pz>>8;data[19]=pz;
    data[20]=sPokeOot.frame>>8;data[21]=sPokeOot.frame;
    data[22]=g->cursor;data[23]=g->trainer_battle;data[24]=(u8)g->turns;
    facing=s->look_x<0 ? 3 : s->look_x>0 ? 1 : s->look_z>0 ? 2 : 0;
    data[25]=PokeOot_InputLocked();
    data[26]=s->warp_pending|(facing<<1)|
        ((play->transitionTrigger!=TRANS_TRIGGER_OFF || play->transitionMode!=TRANS_MODE_OFF) ? 8 : 0);
    data[27]=s->outcome;
    crc=poke_crc32(data,28);data[28]=crc>>24;data[29]=crc>>16;data[30]=crc>>8;data[31]=crc;
    OPEN_DISPS(gfx); gDPPipeSync(OVERLAY_DISP++);gDPSetCycleType(OVERLAY_DISP++,G_CYC_FILL);
    gDPSetRenderMode(OVERLAY_DISP++,G_RM_NOOP,G_RM_NOOP2);
    gDPSetFillColor(OVERLAY_DISP++,0x07FF07FF);gDPFillRectangle(OVERLAY_DISP++,246,4,313,71);
    /* Fill color changes require an RDP pipeline sync. Draw a black field
     * then a single white batch, avoiding per-bit state changes/hazards. */
    gDPPipeSync(OVERLAY_DISP++);gDPSetFillColor(OVERLAY_DISP++,0x00010001);
    gDPFillRectangle(OVERLAY_DISP++,248,6,311,69);
    gDPPipeSync(OVERLAY_DISP++);gDPSetFillColor(OVERLAY_DISP++,0xFFFFFFFF);
    for (i=0;i<256;++i) {
        if (!((data[i/8]>>(7-i%8))&1)) continue;
        x=248+(i%16)*4; y=6+(i/16)*4;
        gDPFillRectangle(OVERLAY_DISP++,x,y,x+3,y+3);
    }
    gDPPipeSync(OVERLAY_DISP++); CLOSE_DISPS(gfx);
}
void PokeOot_Draw(PlayState* play) {
    GraphicsContext* gfx=play->state.gfxCtx; GfxPrint printer;
    PokeGame* g=&sPokeOot.game; PokeIntro* s=&sPokeOot.intro;
    Player* p=GET_PLAYER(play); s32 battling=PokeOot_BattleActive(),i; unsigned choices;
    if (!sPokeOot.initialized || !p || !PokeOot_IsScene(play->sceneId)) return;
    View_Apply(&play->view,VIEW_ALL);
    if (PokeOot_ImportedPallet()) {
        /* Link limbs are suppressed by the shared Red hook, so draw the
         * replacement player even though the authored intro is not running. */
        human(play,MODEL_RED,p->actor.world.pos.x,p->actor.world.pos.y,
              p->actor.world.pos.z,p->actor.shape.rot.y,sPokeOot.gait);
        PokePalletNative_Draw(play);
        return;
    }
    if (battling) draw_battle(play); else draw_world_people(play,p);
    /* Play_Draw queued the native transition overlay before this hook. Keep
     * ordinary UI beneath its fade by omitting it until the room is ready. */
    if (play->transitionTrigger!=TRANS_TRIGGER_OFF || play->transitionMode!=TRANS_MODE_OFF) {
        telemetry(play,p);
        return;
    }
    if (battling) { panel(gfx,8,8,170,45);panel(gfx,155,130,157,45);panel(gfx,8,181,304,52); }
    else { panel(gfx,8,8,264,23);panel(gfx,8,s->talk ? 179 : 214,304,s->talk ? 54 : 19); }
    OPEN_DISPS(gfx); gSPSegment(OVERLAY_DISP++,0,0); GfxPrint_Init(&printer);GfxPrint_Open(&printer,OVERLAY_DISP);
    GfxPrint_SetColor(&printer,255,229,155,255);
    if (battling) {
        const PokeMon* enemy=&g->enemy; const PokeMon* own=&g->party[g->active];
        GfxPrint_SetPosPx(&printer,16,13);GfxPrint_Printf(&printer,"%s %s L%u",g->trainer_battle ? "BLUE" : "WILD",poke_species(enemy->species)->name,enemy->level);
        GfxPrint_SetPosPx(&printer,16,28);GfxPrint_Printf(&printer,"HP %u/%u",enemy->hp,enemy->max_hp);
        GfxPrint_SetPosPx(&printer,163,136);GfxPrint_Printf(&printer,"%s L%u",poke_species(own->species)->name,own->level);
        GfxPrint_SetPosPx(&printer,163,150);GfxPrint_Printf(&printer,"HP %u/%u",own->hp,own->max_hp);
        choices=poke_menu_count(g); GfxPrint_SetColor(&printer,244,239,219,255);
        for(i=0;i<4 && (unsigned)i<choices;++i) {
            GfxPrint_SetPosPx(&printer,16+(i/2)*146,187+(i%2)*12);
            GfxPrint_Printf(&printer,"%c %.15s",g->cursor==i ? '>' : ' ',poke_menu_label(g,i));
        }
        GfxPrint_SetPosPx(&printer,16,216);GfxPrint_Printf(&printer,"%.35s",g->log[POKE_LOG_LINES-1]);
    } else {
        GfxPrint_SetPosPx(&printer,16,15);GfxPrint_Printf(&printer,"%s",gPokeIntroMaps[s->room].name);
        if (s->talk) {
            GfxPrint_SetPosPx(&printer,16,185);GfxPrint_Printf(&printer,"%.35s",poke_intro_speaker(s,g));
            GfxPrint_SetColor(&printer,244,239,219,255);
            for(i=0;i<2;++i) { GfxPrint_SetPosPx(&printer,16,201+i*12);GfxPrint_Printf(&printer,"%.36s",intro_line(s,g,(unsigned)i)); }
        } else {
            GfxPrint_SetPosPx(&printer,16,218);GfxPrint_SetColor(&printer,244,239,219,255);
            GfxPrint_Printf(&printer,"%.36s",poke_intro_objective(s));
        }
    }
    OVERLAY_DISP=GfxPrint_Close(&printer);GfxPrint_Destroy(&printer);CLOSE_DISPS(gfx);
    telemetry(play,p);
}
