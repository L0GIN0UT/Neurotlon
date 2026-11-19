// Прожектор дартса: полупрозрачное затемнение с круглой «дырой». Радиус дыры (в метрах на плоскости мишени)
// игра выставляет каждый кадр по текущему разбросу прицела: чем выше концентрация, тем меньше светлый круг.
// Рисуется на квадрате, лежащем на мишени; _Extent — половина стороны квадрата в метрах.
Shader "Neurotlon/DartsSpotlight"
{
    Properties
    {
        _Radius ("Радиус светлого круга, м", Float) = 0.2
        _Soft ("Мягкость края, м", Float) = 0.025
        _Strength ("Сила затемнения", Range(0, 1)) = 0.74
        _Extent ("Половина стороны квадрата, м", Float) = 0.4
        _Tint ("Цвет затемнения", Color) = (0.02, 0.01, 0.004, 1)
    }

    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "RenderPipeline" = "UniversalPipeline" }

        Pass
        {
            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float _Radius;
                float _Soft;
                float _Strength;
                float _Extent;
                half4 _Tint;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
            };

            Varyings vert(Attributes input)
            {
                Varyings output;
                output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                output.uv = input.uv;
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                float2 p = (input.uv - 0.5) * 2.0 * _Extent;
                float d = length(p);
                float hole = smoothstep(_Radius, _Radius + _Soft, d);
                float fade = 1.0 - smoothstep(_Extent * 0.96, _Extent, d);
                return half4(_Tint.rgb, hole * fade * _Strength);
            }
            ENDHLSL
        }
    }
}
