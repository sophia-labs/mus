# Psychoacoustic operator matrix

| Construct | Current executable operator | Status | Absolute calibration | Interactive intervention |
|---|---|---|---|---|
| Digital level | RMS, sample peak, 4× peak | implemented | no | object gain |
| Programme loudness | pyloudnorm BS.1770 meter | implemented | no pressure calibration; production semantics | target LUFS / gain |
| Psychoacoustic loudness | MoSQITo `loudness_zwtv` + optional ECMA HMS loudness | optional, typed refusal | required | level intervention, then reanalysis |
| Spectral distribution | centroid, slope, rolloff, bandwidth | implemented | no | high shelf |
| Sharpness | Bark relative proxy; MoSQITo DIN time-varying | proxy + optional standard | standard operator requires pressure | high shelf, then reanalysis |
| Timbral brightness | physical correlates only | predictor not yet trained | task-dependent | high shelf |
| Psychoacoustic roughness | Bark modulation proxy; Daniel–Weber; optional ECMA HMS roughness | proxy + optional standards | standard operators require pressure | AM rate/depth |
| Semantic roughness | multidimensional evidence only | listener model pending | task-dependent | AM, shelf, tonal focus |
| Fluctuation strength | Bark slow-modulation proxy | proxy | calibrated standard adapter still pending | slow AM rate/depth |
| Tonality | relative peak proxy; optional ECMA PR/TNR | proxy + optional standards | ECMA operators require pressure | tonal focus / shelf, then reanalysis |
| Pitch salience | pYIN voiced probability proxy | implemented | no | pitch shift / tonal focus |
| Harmonicity | HPSS energy ratio proxy | implemented | no | tonal focus |
| Attack / impulsiveness | 10–90% initial attack, crest factor | implemented | no | onset envelope |
| Timbre dissimilarity | report feature vector | representation foundation | listener task needed | all controls |
| Spatial experience | object position/spread/room | authored scene | rendering/listener conditioned | drag, height, spread, room |
| Transformation quality | receipt + before/after analysis | foundation | protocol conditioned | every intervention |

A `proxy` is not a failed standard metric. It is a separately typed, useful relative model that cannot be cited as the standardized unit or construct without validation.
