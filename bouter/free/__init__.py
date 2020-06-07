from bouter import Experiment
from bouter import utilities, get_scale_mm
import numpy as np
import pandas as pd


class FreelySwimmingExperiment(Experiment):

    @property
    def n_tail_segments(self):
        return self["tracking+fish_tracking"]["n_segments"] - 1

    @property
    def n_fish(self):
        return self["tracking+fish_tracking"]["n_fish_max"]


    def _extract_bout(self, s, e, n_segments, i_fish=0, scale=1.0, dt=None):
        bout = self._rename_fish(self.behavior_log.iloc[s:e], i_fish, n_segments)
        # scale to physical coordinates
        if dt is None:
            dt = (bout.t.values[-1] - bout.t.values[0]) / bout.shape[0]

        # pixels are scaled to millimeters (columns x, vx, y and vy)
        bout.iloc[:, 1:5] *= scale
        # velocities are additionally divided by the time difference to get mm/s
        bout.iloc[:, 2:7:2] /= dt
        return bout


    def _fish_column_names(self, i_fish, n_segments):
        return [
                   "f{:d}_x".format(i_fish),
                   "f{:d}_vx".format(i_fish),
                   "f{:d}_y".format(i_fish),
                   "f{:d}_vy".format(i_fish),
                   "f{:d}_theta".format(i_fish),
                   "f{:d}_vtheta".format(i_fish),
               ] + ["f{:d}_theta_{:02d}".format(i_fish, i) for i in range(n_segments)]


    def _fish_renames(self, i_fish, n_segments):
        return dict(
            {
                "f{:d}_x".format(i_fish): "x",
                "f{:d}_vx".format(i_fish): "vx",
                "f{:d}_y".format(i_fish): "y",
                "f{:d}_vy".format(i_fish): "vy",
                "f{:d}_theta".format(i_fish): "theta",
                "f{:d}_vtheta".format(i_fish): "vtheta",
            },
            **{
                "f{:d}_theta_{:02d}".format(i_fish, i): "theta_{:02d}".format(i)
                for i in range(n_segments)
            }
        )


    def _rename_fish(self, df, i_fish, n_segments):
        return df.filter(["t"] + self._fish_column_names(i_fish, n_segments)).rename(
            columns=self._fish_renames(i_fish, n_segments)
        )


    def extract_bouts(
        self,
        max_interpolate=2,
        window_size=7,
        recalculate_vel=False,
        median_vel=False,
        scale=None,
        threshold=1,
        **kwargs
    ):
        """ Extracts all bouts from a freely-swimming tracking experiment

        :param exp: the experiment object
        :param max_interpolate: number of points to interpolate if surrounded by NaNs in tracking
        :param scale: mm per pixel, recalculated by default
        :param max_frames: the maximum numbers of frames to process, useful for debugging
        :param threshold: velocity threshold in mm/s
        :param min_duration: minimal number of frames for a bout
        :param pad_before: number of frames that gets added before
        :param pad_after: number of frames added after

        :return: tuple: (list of single bout dataframes, list of boolean arrays marking if the
         bout i follows bout i-1)
        """

        df = self.behavior_log

        scale = scale or get_scale_mm(self)

        dt = np.mean(np.diff(df.t[100:200]))

        n_fish = self.n_fish
        n_segments = self.n_tail_segments
        dfint = df.interpolate("linear", limit=max_interpolate, limit_area="inside")
        bouts = []
        continuous = []
        for i_fish in range(n_fish):
            if recalculate_vel:
                for thing in ["x", "y", "theta"]:
                    dfint["f{}_v{}".format(i_fish, thing)] = np.r_[
                        np.diff(dfint["f{}_{}".format(i_fish, thing)]), 0
                    ]

            vel2 = (
                dfint["f{}_vx".format(i_fish)] ** 2 + dfint["f{}_vy".format(i_fish)] ** 2
            ) * ((scale / dt) ** 2)
            if median_vel:
                vel2 = vel2.rolling(window=window_size, min_periods=1).median()
            bout_locations, continuity = utilities.extract_segments_above_threshold(
                vel2.values, threshold=threshold ** 2, **kwargs
            )
            all_bouts_fish = [
                self._extract_bout(s, e, n_segments, i_fish, scale)
                for s, e in bout_locations
            ]
            bouts.append(all_bouts_fish)
            continuous.append(np.array(continuity))

        return bouts, continuous


    def summarize_bouts(self, bouts, continuity=None):
        """ Makes a summary of all extracted bouts: basic kinematic parameters
        and timing

        :param bouts:a list of lists of fish
        :param continuity:
        :return: a dataframe containing all bouts
        """
        headers = [
            "t_start",
            "x_start",
            "y_start",
            "theta_start",
            "t_end",
            "x_end",
            "y_end",
            "theta_end",
        ]

        # an array is preallocated loop through the bouts
        bout_data = np.empty(
            (np.sum([len(bouts[i]) for i in range(len(bouts))]), len(headers))
        )
        n_summarized_bouts = 0
        for i_fish in range(len(bouts)):
            for i_bout, bout in enumerate(bouts[i_fish]):
                # slices from 0 to 4 are the start parameters, from 4 to 8 the end parameters
                for sl, idx in zip([slice(0, 4), slice(4, 8)], [0, -1]):
                    bout_data[n_summarized_bouts + i_bout, sl] = [
                        bout.t.iloc[idx],
                        bout.x.iloc[idx],
                        bout.y.iloc[idx],
                        bout.theta.iloc[idx],
                    ]
            n_summarized_bouts += len(bouts[i_fish])

        bout_data_df = pd.DataFrame(bout_data, columns=headers)
        if continuity:
            bout_data_df["follows_previous"] = np.concatenate(continuity)

        # if there are multiple fish tracked in the same experiments, assign the
        # identities (there is no guarantee that the identity will be consistent if the
        # fish cross or go outside of the visible region)
        if len(bouts) > 1:
            origin_fish = np.concatenate(
                [np.full(len(bouts[i]), i, dtype=np.uint8) for i in range(len(bouts))]
            )
            bout_data_df.insert(0, "i_fish", origin_fish)

        return bout_data_df
