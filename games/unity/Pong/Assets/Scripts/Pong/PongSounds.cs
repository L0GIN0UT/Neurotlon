using UnityEngine;

namespace Neurotlon.Games.Pong
{
    // Звуки игры. Клипы синтезированы скриптом (ArtSource/Audio/make_sounds.py), внешних файлов нет.
    public sealed class PongSounds : MonoBehaviour
    {
        [SerializeField] AudioSource source;
        [SerializeField] AudioClip paddleHit;
        [SerializeField] AudioClip tableBounce;
        [SerializeField] AudioClip wallBounce;
        [SerializeField] AudioClip point;
        [SerializeField] AudioClip overtime;
        [SerializeField] AudioClip win;

        public void Play(PongEventKind kind)
        {
            AudioClip clip = null;
            switch (kind)
            {
                case PongEventKind.PaddleHit: clip = paddleHit; break;
                case PongEventKind.WallBounce: clip = wallBounce; break;
                case PongEventKind.Point: clip = point; break;
                case PongEventKind.Overtime: clip = overtime; break;
                case PongEventKind.GameOver: clip = win; break;
            }
            PlayClip(clip);
        }

        public void PlayTableBounce()
        {
            PlayClip(tableBounce);
        }

        void PlayClip(AudioClip clip)
        {
            if (clip != null && source != null) source.PlayOneShot(clip);
        }
    }
}
