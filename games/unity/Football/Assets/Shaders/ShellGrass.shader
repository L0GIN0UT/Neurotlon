// Объёмная трава «оболочками» (shell texturing): одна сетка поля повторена несколькими слоями, каждый слой чуть выше предыдущего
// и вырезается шумом травинок. Вблизи получается густая объёмная трава, вдали слои «схлопываются» в обычную текстуру.
// Слой вершины берётся из второй UV-координаты (uv1.x от 0 у земли до 1 у кончиков). Полосы покоса — отдельная текстура на всё поле.
//
// Против ряби и полос при взгляде под малым углом:
//  - края травинок мягкие (AlphaToMask + MSAA), а не жёсткий вырез;
//  - слои гаснут по размеру пикселя: когда травинка мельче пикселя, рисуется только основание со средним цветом;
//  - плитка текстуры берётся дважды в разном масштабе и повороте, чтобы не было повторяющихся полос.
Shader "Neurotlon/ShellGrass"
{
    Properties
    {
        [MainTexture] _BaseMap ("Газон (плитка)", 2D) = "white" {}
        _StripeMap ("Полосы покоса (на всё поле)", 2D) = "white" {}
        _TileSize ("Размер плитки, м", Float) = 1.4
        _FieldCenter ("Центр поля XZ, м", Vector) = (0, 0, 0, 0)
        _FieldSize ("Размер поля XZ, м", Vector) = (62, 44, 0, 0)
        _Height ("Высота травы, м", Float) = 0.04
        _Density ("Травинок на метр", Float) = 70
        _Near ("Полная высота до, м", Float) = 5
        _Far ("Слои пропадают на, м", Float) = 12
        _Root ("Цвет у корня", Color) = (0.40, 0.55, 0.23, 1)
        _Tip ("Цвет кончиков", Color) = (1.18, 1.18, 1.02, 1)
        _Ambient ("Окружающий свет", Range(0, 2)) = 1.0
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" "RenderPipeline" = "UniversalPipeline" }

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }
            Cull Off
            ZWrite On
            AlphaToMask On

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
            #pragma multi_compile_fragment _ _SHADOWS_SOFT
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            TEXTURE2D(_BaseMap);   SAMPLER(sampler_BaseMap);
            TEXTURE2D(_StripeMap); SAMPLER(sampler_StripeMap);

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                float _TileSize;
                float4 _FieldCenter;
                float4 _FieldSize;
                float _Height;
                float _Density;
                float _Near;
                float _Far;
                half4 _Root;
                half4 _Tip;
                half _Ambient;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 layer : TEXCOORD1;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
                float2 layerFade : TEXCOORD1;
            };

            float Hash(float2 p)
            {
                return frac(sin(dot(p, float2(12.9898, 78.233))) * 43758.5453);
            }

            // плавный шум для крупных пятен яркости (без повторов плитки)
            float ValueNoise(float2 p)
            {
                float2 i = floor(p);
                float2 f = frac(p);
                f = f * f * (3.0 - 2.0 * f);
                return lerp(lerp(Hash(i), Hash(i + float2(1, 0)), f.x), lerp(Hash(i + float2(0, 1)), Hash(i + float2(1, 1)), f.x), f.y);
            }

            Varyings vert(Attributes input)
            {
                Varyings output;
                float3 positionWS = TransformObjectToWorld(input.positionOS.xyz);
                float distanceToCamera = distance(_WorldSpaceCameraPos, positionWS);
                float fade = 1.0 - saturate((distanceToCamera - _Near) / max(0.01, _Far - _Near));
                positionWS.y += input.layer.x * _Height * fade;                 // слой поднимается тем выше, чем ближе камера
                output.positionWS = positionWS;
                output.positionCS = TransformWorldToHClip(positionWS);
                output.layerFade = float2(input.layer.x, fade);
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                float layer = input.layerFade.x;
                // размер пикселя в травинках: когда он больше ~0,45, травинки мельче пикселя и дают рябь, слои гасим
                float2 footprint = fwidth(input.positionWS.xz * _Density);
                float resolvable = 1.0 - saturate((max(footprint.x, footprint.y) - 0.45) / 0.55);
                float fade = input.layerFade.y * resolvable;
                float alpha = 1.0;
                if (layer > 0.001)
                {
                    if (fade < 0.02) discard;                                    // далеко: слой не рисуем совсем
                    float2 cell = floor(input.positionWS.xz * _Density);
                    float rnd = Hash(cell);
                    float bladeHeight = lerp(0.2, 1.0, rnd);                     // у травинок разная высота
                    float inner = 1.0 - saturate(length(frac(input.positionWS.xz * _Density) - 0.5) * 2.0);
                    float taper = bladeHeight * (0.55 + 0.45 * inner);           // травинка сужается к кончику
                    alpha = saturate((taper * fade - layer) / 0.08 + 0.5);        // мягкий край для MSAA
                    if (alpha <= 0.01) discard;
                }

                float2 tileUV = input.positionWS.xz / _TileSize * _BaseMap_ST.xy;
                float2 rotatedUV = float2(tileUV.x * 0.8 - tileUV.y * 0.6, tileUV.x * 0.6 + tileUV.y * 0.8) * 0.37 + 0.31;      // другой масштаб и поворот
                half3 albedo = lerp(SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, tileUV).rgb, SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, rotatedUV).rgb, 0.4);
                float macro = 0.88 + 0.24 * ValueNoise(input.positionWS.xz * 0.22);                                             // крупные пятна яркости
                float2 fieldUV = (input.positionWS.xz - _FieldCenter.xz) / _FieldSize.xy + 0.5;
                half3 stripes = SAMPLE_TEXTURE2D(_StripeMap, sampler_StripeMap, fieldUV).rgb;
                float tone = lerp(0.5, layer, fade);                             // где слоёв нет, основание красится средним цветом
                half3 color = albedo * stripes * macro * lerp(_Root.rgb, _Tip.rgb, tone);

                float4 shadowCoord = TransformWorldToShadowCoord(input.positionWS);
                Light mainLight = GetMainLight(shadowCoord);
                half3 up = half3(0, 1, 0);
                half3 diffuse = mainLight.color * (saturate(dot(up, mainLight.direction)) * mainLight.shadowAttenuation);
                half3 ambient = SampleSH(up) * _Ambient;
                return half4(color * (diffuse + ambient), alpha);
            }
            ENDHLSL
        }
    }
}
