import sys

import numpy as np
import matplotlib.pyplot as plt

import csv

from pygenn import genn_model, genn_wrapper
from pygenn.genn_wrapper.Models import VarAccess_READ_ONLY
from time import perf_counter

from common import (
    izhikevich_dopamine_model,
    izhikevich_stdp_model,
    build_model,
    get_params,
    plot,
    convert_spikes,
)

# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------


def get_start_end_stim(stim_counts):
    end_stimuli = np.cumsum(stim_counts)
    start_stimuli = np.empty_like(end_stimuli)
    start_stimuli[0] = 0
    start_stimuli[1:] = end_stimuli[0:-1]

    return start_stimuli, end_stimuli


# ----------------------------------------------------------------------------
# Custom models
# ----------------------------------------------------------------------------
stim_noise_model = genn_model.create_custom_current_source_class(
    "stim_noise",
    param_names=["n", "stimMagnitude"],
    var_name_types=[
        ("startStim", "unsigned int"),
        ("endStim", "unsigned int", VarAccess_READ_ONLY),
    ],
    extra_global_params=[("stimTimes", "scalar*")],
    injection_code="""
        scalar current = ($(gennrand_uniform) * $(n) * 2.0) - $(n);
        if($(startStim) != $(endStim) && $(t) >= $(stimTimes)[$(startStim)]) {
           current += $(stimMagnitude);
           $(startStim)++;
        }
        $(injectCurrent, current);
        """,
)

# ----------------------------------------------------------------------------
# Stimuli generation
# ----------------------------------------------------------------------------
# Get standard model parameters
params = get_params(build_model=True, measure_timing=False, use_genn_recording=True)
if "seed" in params:
    np.random.seed(params["seed"])

# Generate stimuli sets of neuron IDs
num_cells = params["num_excitatory"] + params["num_inhibitory"]
stim_gen_start_time = perf_counter()
input_sets = [
    np.random.choice(num_cells, params["stimuli_set_size"], replace=False)
    for _ in range(params["num_stimuli_sets"])
]
input_sets.append(np.array([]))

params["dt1"] = int(sys.argv[1])
params["dt2"] = int(sys.argv[2])
target_triplet_set = np.array([0, 1, 2, params["dt1"], params["dt2"]])
stimuli_triplet_set_timing = []
for d1 in range(0, 6, 1):
    for d2 in range(0, 6, 1):
        stimuli_triplet_set_timing.append(np.array([0, 1, 2, d1, d2]))
for d1 in range(0, 6, 1):
    stimuli_triplet_set_timing.append(
        np.array([0, 1, params["num_stimuli_sets"], d1, 0])
    )
for d2 in range(0, 6, 1):
    stimuli_triplet_set_timing.append(
        np.array([0, params["num_stimuli_sets"], 2, 0, d2])
    )
stimuli_triplet_set_timing.append(
    np.array(
        [
            0,
            params["num_stimuli_sets"],
            params["num_stimuli_sets"],
            params["dt1"],
            params["dt2"],
        ]
    )
)
stimuli_triplet_set_timing.append(
    np.array(
        [
            1,
            params["num_stimuli_sets"],
            params["num_stimuli_sets"],
            params["dt1"],
            params["dt2"],
        ]
    )
)
stimuli_triplet_set_timing.append(
    np.array(
        [
            2,
            params["num_stimuli_sets"],
            params["num_stimuli_sets"],
            params["dt1"],
            params["dt2"],
        ]
    )
)
stimuli_triplet_set_timing.append(np.array([4, 5, 6, params["dt1"], params["dt2"]]))


# Lists of stimulus and reward times for use when plotting
start_stimulus_times = []
end_stimulus_times = []
start_reward_times = []
end_reward_times = []

# Create list for each neuron
neuron_stimuli_times = [[] for _ in range(num_cells)]
total_num_exc_stimuli = 0
total_num_inh_stimuli = 0

# Create zeroes numpy array to hold reward timestep bitmask
reward_timesteps = np.zeros((params["duration_timestep"] + 31) // 32, dtype=np.uint32)

# Loop while stimuli are within simulation duration

next_stimuli_timestep = np.random.randint(
    params["min_inter_stimuli_interval_timestep"],
    params["max_inter_stimuli_interval_timestep"],
)
cycle_num = 0
while next_stimuli_timestep < params["duration_timestep"]:
    # Pick a stimuli set to present at this timestep
    if cycle_num != 0 and cycle_num % 100 == 0:
        stimuli_set = target_triplet_set
    else:
        stimuli_set = np.append(
            np.random.choice(params["num_stimuli_sets"], 3, replace=False),
            [params["dt1"], params["dt2"]],
        )

    if next_stimuli_timestep > (
        params["duration_timestep"] - params["record_time_timestep"]
    ):
        stimuli_set = stimuli_triplet_set_timing[
            np.random.randint(0, len(stimuli_triplet_set_timing))
        ]

    # Loop through neurons in stimuli set and add time to list
    for n in input_sets[stimuli_set[0]]:
        neuron_stimuli_times[n].append(next_stimuli_timestep * params["timestep_ms"])
    for n in input_sets[stimuli_set[1]]:
        neuron_stimuli_times[n].append(
            (next_stimuli_timestep + stimuli_set[3]) * params["timestep_ms"]
        )
    for n in input_sets[stimuli_set[2]]:
        neuron_stimuli_times[n].append(
            (next_stimuli_timestep + stimuli_set[3] + stimuli_set[4])
            * params["timestep_ms"]
        )

    # Count the number of excitatory neurons in input set and add to total
    num_exc_in_input_set = np.sum(input_sets[stimuli_set[0]] < params["num_excitatory"])
    total_num_exc_stimuli += num_exc_in_input_set
    total_num_inh_stimuli += num_cells - num_exc_in_input_set

    # If we should be recording at this point, add stimuli to list
    if next_stimuli_timestep < params["record_time_timestep"]:
        start_stimulus_times.append(
            (
                next_stimuli_timestep * params["timestep_ms"],
                stimuli_set[0],
                stimuli_set[1],
                stimuli_set[2],
                stimuli_set[3],
                stimuli_set[4],
            )
        )
    elif next_stimuli_timestep > (
        params["duration_timestep"] - params["record_time_timestep"]
    ):
        end_stimulus_times.append(
            (
                next_stimuli_timestep * params["timestep_ms"],
                stimuli_set[0],
                stimuli_set[1],
                stimuli_set[2],
                stimuli_set[3],
                stimuli_set[4],
            )
        )

    # If this is the rewarded stimuli
    if (stimuli_set == target_triplet_set).all() and next_stimuli_timestep <= (
        params["duration_timestep"] - params["record_time_timestep"]
    ):
        # Determine time of next reward
        reward_timestep = next_stimuli_timestep + np.random.randint(
            params["max_reward_delay_timestep"]
        )

        # If this is within simulation
        if reward_timestep < params["duration_timestep"]:
            # Set bit in reward timesteps bitmask
            reward_timesteps[reward_timestep // 32] |= 1 << (reward_timestep % 32)

            # If we should be recording at this point, add reward to list
            if reward_timestep < params["record_time_timestep"]:
                start_reward_times.append(reward_timestep * params["timestep_ms"])
            elif reward_timestep > (
                params["duration_timestep"] - params["record_time_timestep"]
            ):
                end_reward_times.append(reward_timestep * params["timestep_ms"])

    # Advance to next stimuli
    next_stimuli_timestep += np.random.randint(
        params["min_inter_stimuli_interval_timestep"],
        params["max_inter_stimuli_interval_timestep"],
    )
    cycle_num += 1

# Count stimuli each neuron should emit
neuron_stimuli_counts = [len(n) for n in neuron_stimuli_times]

stim_gen_end_time = perf_counter()
print(
    "Stimulus generation time: %fms"
    % ((stim_gen_end_time - stim_gen_start_time) * 1000.0)
)

# ----------------------------------------------------------------------------
# Network creation
# ----------------------------------------------------------------------------
# Assert that duration is a multiple of record time
assert (params["duration_timestep"] % params["record_time_timestep"]) == 0

# Build base model
model, e_pop, i_pop, e_e_pop, e_i_pop = build_model(
    "izhikevich_pavlovian_gpu_stim", params, reward_timesteps
)

# Current source parameters
curr_source_params = {"n": 6.5, "stimMagnitude": params["stimuli_current"]}

# Calculate start and end indices of stimuli to be injected by each current source
start_exc_stimuli, end_exc_stimuli = get_start_end_stim(
    neuron_stimuli_counts[: params["num_excitatory"]]
)
start_inh_stimuli, end_inh_stimuli = get_start_end_stim(
    neuron_stimuli_counts[params["num_excitatory"] :]
)

# Current source initial state
exc_curr_source_init = {"startStim": start_exc_stimuli, "endStim": end_exc_stimuli}
inh_curr_source_init = {"startStim": start_inh_stimuli, "endStim": end_inh_stimuli}

# Add background current sources
e_curr_pop = model.add_current_source(
    "ECurr", stim_noise_model, "E", curr_source_params, exc_curr_source_init
)
i_curr_pop = model.add_current_source(
    "ICurr", stim_noise_model, "I", curr_source_params, inh_curr_source_init
)

# Set stimuli times
e_curr_pop.set_extra_global_param(
    "stimTimes", np.hstack(neuron_stimuli_times[: params["num_excitatory"]])
)
i_curr_pop.set_extra_global_param(
    "stimTimes", np.hstack(neuron_stimuli_times[params["num_excitatory"] :])
)

if params["build_model"]:
    print("Building model")
    model.build()

# ----------------------------------------------------------------------------
# Simulation
# ----------------------------------------------------------------------------
# Load model, allocating enough memory for recording
print("Loading model")
model.load(num_recording_timesteps=params["record_time_timestep"])

print("Simulating")
# Loop through timesteps
sim_start_time = perf_counter()
start_exc_spikes = None if params["use_genn_recording"] else []
start_inh_spikes = None if params["use_genn_recording"] else []
end_exc_spikes = None if params["use_genn_recording"] else []
end_inh_spikes = None if params["use_genn_recording"] else []

while model.t < params["duration_ms"]:
    if params["use_weight_record"] == True:
        if model.t % (60 * 1000) == 0:
            e_e_pop.pull_var_from_device("g")
            e_e_pop.pull_connectivity_from_device()

            g_e_e = e_e_pop.get_var_values("g")
            row_e_e = np.array(e_e_pop.get_sparse_pre_inds())
            col_e_e = np.array(e_e_pop.get_sparse_post_inds())

            np.save(
                "%s/%s/%d,%dms interval, weight in %ds_data"
                % (
                    params["cwd"],
                    params["record_path"],
                    params["dt1"],
                    params["dt2"],
                    ((model.t // (1 * 1000)) * 1),
                ),
                g_e_e,
            )
            np.save(
                "%s/%s/%d,%dms interval, weight in %ds_row"
                % (
                    params["cwd"],
                    params["record_path"],
                    params["dt1"],
                    params["dt2"],
                    ((model.t // (1 * 1000)) * 1),
                ),
                row_e_e,
            )
            np.save(
                "%s/%s/%d,%dms interval, weight in %ds_col"
                % (
                    params["cwd"],
                    params["record_path"],
                    params["dt1"],
                    params["dt2"],
                    ((model.t // (1 * 1000)) * 1),
                ),
                col_e_e,
            )

    # Simulation
    model.step_time()

    if params["use_genn_recording"]:
        # If we've just finished simulating the initial recording interval
        if model.timestep == params["record_time_timestep"]:
            # Download recording data
            model.pull_recording_buffers_from_device()

            start_exc_spikes = e_pop.spike_recording_data
            start_inh_spikes = i_pop.spike_recording_data
        # Otherwise, if we've finished entire simulation
        elif model.timestep == params["duration_timestep"]:
            # Download recording data
            model.pull_recording_buffers_from_device()

            end_exc_spikes = e_pop.spike_recording_data
            end_inh_spikes = i_pop.spike_recording_data
    else:
        if model.timestep <= params["record_time_timestep"]:
            e_pop.pull_current_spikes_from_device()
            i_pop.pull_current_spikes_from_device()
            start_exc_spikes.append(np.copy(e_pop.current_spikes))
            start_inh_spikes.append(np.copy(i_pop.current_spikes))
        elif model.timestep > (
            params["duration_timestep"] - params["record_time_timestep"]
        ):
            e_pop.pull_current_spikes_from_device()
            i_pop.pull_current_spikes_from_device()
            end_exc_spikes.append(np.copy(e_pop.current_spikes))
            end_inh_spikes.append(np.copy(i_pop.current_spikes))

sim_end_time = perf_counter()
print("Simulation time: %fms" % ((sim_end_time - sim_start_time) * 1000.0))

if not params["use_genn_recording"]:
    start_timesteps = np.arange(0.0, params["record_time_ms"], params["timestep_ms"])
    end_timesteps = np.arange(
        params["duration_ms"] - params["record_time_ms"],
        params["duration_ms"],
        params["timestep_ms"],
    )

    start_exc_spikes = convert_spikes(start_exc_spikes, start_timesteps)
    start_inh_spikes = convert_spikes(start_inh_spikes, start_timesteps)
    end_exc_spikes = convert_spikes(end_exc_spikes, end_timesteps)
    end_inh_spikes = convert_spikes(end_inh_spikes, end_timesteps)

if params["measure_timing"]:
    print("\tInit:%f" % (1000.0 * model.init_time))
    print("\tSparse init:%f" % (1000.0 * model.init_sparse_time))
    print("\tNeuron simulation:%f" % (1000.0 * model.neuron_update_time))
    print("\tPresynaptic update:%f" % (1000.0 * model.presynaptic_update_time))
    print("\tPostsynaptic update:%f" % (1000.0 * model.postsynaptic_update_time))

# ----------------------------------------------------------------------------
# Plotting
# ----------------------------------------------------------------------------
# plot(
#     start_exc_spikes,
#     start_inh_spikes,
#     end_exc_spikes,
#     end_inh_spikes,
#     start_stimulus_times,
#     start_reward_times,
#     end_stimulus_times,
#     end_reward_times,
#     20000.0,
#     params,
# )

# Save plot
# plt.savefig(f"{params['cwd']}/{params['fig_path']}/{params['dt1']}_{params['dt2']}_plot.jpg")

# Read rewards
with open(
    f"{params['cwd']}/{params['csv_path']}/{params['dt1']}_{params['dt2']}_izhikevich_stimulus_times.csv",
    "w",
    newline="\n",
) as csvfile:
    spamwriter = csv.writer(csvfile, delimiter=",")
    for stimuls in start_stimulus_times:
        spamwriter.writerow(
            [stimuls[0], stimuls[1], stimuls[2], stimuls[3], stimuls[4], stimuls[5]]
        )
    for stimuls in end_stimulus_times:
        spamwriter.writerow(
            [stimuls[0], stimuls[1], stimuls[2], stimuls[3], stimuls[4], stimuls[5]]
        )

with open(
    f"{params['cwd']}/{params['csv_path']}/{params['dt1']}_{params['dt2']}_izhikevich_reward_times.csv",
    "w",
    newline="\n",
) as csvfile:
    spamwriter = csv.writer(csvfile, delimiter=",")
    for reward in start_reward_times:
        spamwriter.writerow([reward])
    for reward in end_reward_times:
        spamwriter.writerow([reward])

with open(
    f"{params['cwd']}/{params['csv_path']}/{params['dt1']}_{params['dt2']}_izhikevich_e_spikes.csv",
    "w",
    newline="\n",
) as csvfile:
    spamwriter = csv.writer(csvfile, delimiter=",")
    spamwriter.writerow(["Time [ms]", " Neuron ID"])
    for time, ids in zip(start_exc_spikes[0], start_exc_spikes[1]):
        spamwriter.writerow([time, ids])
    for time, ids in zip(end_exc_spikes[0], end_exc_spikes[1]):
        spamwriter.writerow([time, ids])

with open(
    f"{params['cwd']}/{params['csv_path']}/{params['dt1']}_{params['dt2']}_izhikevich_i_spikes.csv",
    "w",
    newline="\n",
) as csvfile:
    spamwriter = csv.writer(csvfile, delimiter=",")
    spamwriter.writerow(["Time [ms]", " Neuron ID"])
    for time, ids in zip(start_inh_spikes[0], start_inh_spikes[1]):
        spamwriter.writerow([time, ids])
    for time, ids in zip(end_inh_spikes[0], end_inh_spikes[1]):
        spamwriter.writerow([time, ids])
