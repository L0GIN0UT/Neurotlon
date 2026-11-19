using UnityEngine;

namespace Neurotlon.Games.Darts
{
    // Звуки игры. Клипы синтезированы скриптом (ArtSource/Audio/make_sounds.py), внешних файлов нет.
    public sealed class DartsSounds : MonoBehaviour
    {
        [SerializeField] AudioSource source;
        [SerializeField] AudioClip throwClip;
        [SerializeField] AudioClip hit;
        [SerializeField] AudioClip bull;
        [SerializeField] AudioClip miss;
        [SerializeField] AudioClip finish;

        public void Play(DartsEvent e)
        {
            switch (e.Kind)
            {
                case DartsEventKind.Throw: PlayClip(throwClip); break;
                case DartsEventKind.Hit: PlayClip(e.Points >= 2 ? bull : (e.Points == 1 ? hit : miss)); break;
                case DartsEventKind.GameOver: PlayClip(finish); break;
            }
        }

        void PlayClip(AudioClip clip)
        {
            if (clip != null && source != null) source.PlayOneShot(clip);
        }
    }
}
