# -------------------------------------------------------------------------------
# Copyright (c) 2017, Battelle Memorial Institute All rights reserved.
# Battelle Memorial Institute (hereinafter Battelle) hereby grants permission to any person or entity
# lawfully obtaining a copy of this software and associated documentation files (hereinafter the
# Software) to redistribute and use the Software in source and binary forms, with or without modification.
# Such person or entity may use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and may permit others to do so, subject to the following conditions:
# Redistributions of source code must retain the above copyright notice, this list of conditions and the
# following disclaimers.
# Redistributions in binary form must reproduce the above copyright notice, this list of conditions and
# the following disclaimer in the documentation and/or other materials provided with the distribution.
# Other than as used herein, neither the name Battelle Memorial Institute or Battelle may be used in any
# form whatsoever without the express written consent of Battelle.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL
# BATTELLE OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
# GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
# OF THE POSSIBILITY OF SUCH DAMAGE.
# General disclaimer for use with OSS licenses
#
# This material was prepared as an account of work sponsored by an agency of the United States Government.
# Neither the United States Government nor the United States Department of Energy, nor Battelle, nor any
# of their employees, nor any jurisdiction or organization that has cooperated in the development of these
# materials, makes any warranty, express or implied, or assumes any legal liability or responsibility for
# the accuracy, completeness, or usefulness or any information, apparatus, product, software, or process
# disclosed, or represents that its use would not infringe privately owned rights.
#
# Reference herein to any specific commercial product, process, or service by trade name, trademark, manufacturer,
# or otherwise does not necessarily constitute or imply its endorsement, recommendation, or favoring by the United
# States Government or any agency thereof, or Battelle Memorial Institute. The views and opinions of authors expressed
# herein do not necessarily state or reflect those of the United States Government or any agency thereof.
#
# PACIFIC NORTHWEST NATIONAL LABORATORY operated by BATTELLE for the
# UNITED STATES DEPARTMENT OF ENERGY under Contract DE-AC05-76RL01830
# -------------------------------------------------------------------------------
"""
Created on Jan 19, 2018

@author: Craig Allwardt
"""

__version__ = "0.0.8"

import argparse
import json
import logging
import sys
import time

from gridappsd import GridAPPSD, DifferenceBuilder, utils
from gridappsd.topics import simulation_input_topic, simulation_output_topic, simulation_log_topic, simulation_output_topic

DEFAULT_MESSAGE_PERIOD = 10

# logging.basicConfig(stream=sys.stdout, level=logging.DEBUG,
#                     format="%(asctime)s - %(name)s;%(levelname)s|%(message)s",
#                     datefmt="%Y-%m-%d %H:%M:%S")
# Only log errors to the stomp logger.
logging.getLogger('stomp.py').setLevel(logging.ERROR)

_log = logging.getLogger(__name__)


class CapacitorToggler(object):
    """ A simple class that handles publishing forward and reverse differences

    The object should be used as a callback from a GridAPPSD object so that the
    on_message function will get called each time a message from the simulator.  During
    the execution of on_meessage the `CapacitorToggler` object will publish a
    message to the simulation_input_topic with the forward and reverse difference specified.
    """

    def __init__(self, simulation_id, gridappsd_obj, capacitor_list):
        """ Create a ``CapacitorToggler`` object

        This object should be used as a subscription callback from a ``GridAPPSD``
        object.  This class will toggle the capacitors passed to the constructor
        off and on every five messages that are received on the ``fncs_output_topic``.

        Note
        ----
        This class does not subscribe only publishes.

        Parameters
        ----------
        simulation_id: str
            The simulation_id to use for publishing to a topic.
        gridappsd_obj: GridAPPSD
            An instatiated object that is connected to the gridappsd message bus
            usually this should be the same object which subscribes, but that
            isn't required.
        capacitor_list: list(str)
            A list of capacitors mrids to turn on/off
        """
        self._gapps = gridappsd_obj
        self._cap_list = capacitor_list
        self._message_count = 0
        self._last_toggle_on = False
        self._open_diff = DifferenceBuilder(simulation_id)
        self._close_diff = DifferenceBuilder(simulation_id)
        self._publish_to_topic = simulation_input_topic(simulation_id)
        _log.info("Building cappacitor list")
        for cap_mrid in capacitor_list:
            _log.debug(f"Adding cap sum difference to list: {cap_mrid}")
            self._open_diff.add_difference(cap_mrid, "ShuntCompensator.sections", 0, 1)
            self._close_diff.add_difference(cap_mrid, "ShuntCompensator.sections", 1, 0)
            # self._open_diff.add_difference(cap_mrid, "ShuntCompensator.sections", 1, 0)
            # self._close_diff.add_difference(cap_mrid, "ShuntCompensator.sections", 0, 1)

    def on_message(self, headers, message):
        """ Handle incoming messages on the simulation_output_topic for the simulation_id

        Parameters
        ----------
        headers: dict
            A dictionary of headers that could be used to determine topic of origin and
            other attributes.
        message: object
            A data structure following the protocol defined in the message structure
            of ``GridAPPSD``.  Most message payloads will be serialized dictionaries, but that is
            not a requirement.
        """

        self._message_count += 1
        _log.debug(f"new message count is: {self._message_count}")

        # Every message_period messages we are going to turn the capcitors on or off depending
        # on the current capacitor state.
        if self._message_count % message_period == 0:
            if self._last_toggle_on:
                _log.debug("count: {} toggling off".format(self._message_count))
                msg = self._close_diff.get_message(epoch=message['message']['timestamp'])
                self._last_toggle_on = False
            else:
                _log.debug("count: {} toggling on".format(self._message_count))
                msg = self._open_diff.get_message(epoch=message['message']['timestamp'])
                self._last_toggle_on = True

            self._gapps.send(self._publish_to_topic, json.dumps(msg))


def get_capacitor_mrids(gridappsd_obj, mrid):
    query = """
    # capacitors (does not account for 2+ unequal phases on same LinearShuntCompensator) - DistCapacitor
PREFIX r:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX c:  <http://iec.ch/TC57/CIM100#>
SELECT 
#?name ?basev ?nomu ?bsection ?bus ?conn ?grnd ?phs ?ctrlenabled ?discrete ?mode ?deadband ?setpoint ?delay ?monclass ?moneq ?monbus ?monphs 

?id ?fdrid WHERE {
 ?s r:type c:LinearShuntCompensator.
# feeder selection options - if all commented out, query matches all feeders
VALUES ?fdrid {"%s"}
 ?s c:Equipment.EquipmentContainer ?fdr.
 ?fdr c:IdentifiedObject.mRID ?fdrid.
 ?s c:IdentifiedObject.name ?name.
 ?s c:ConductingEquipment.BaseVoltage ?bv.
 ?bv c:BaseVoltage.nominalVoltage ?basev.
 ?s c:ShuntCompensator.nomU ?nomu. 
 ?s c:LinearShuntCompensator.bPerSection ?bsection. 
 ?s c:ShuntCompensator.phaseConnection ?connraw.
   bind(strafter(str(?connraw),"PhaseShuntConnectionKind.") as ?conn)
 ?s c:ShuntCompensator.grounded ?grnd.
 OPTIONAL {?scp c:ShuntCompensatorPhase.ShuntCompensator ?s.
 ?scp c:ShuntCompensatorPhase.phase ?phsraw.
   bind(strafter(str(?phsraw),"SinglePhaseKind.") as ?phs) }
 OPTIONAL {?ctl c:RegulatingControl.RegulatingCondEq ?s.
          ?ctl c:RegulatingControl.discrete ?discrete.
          ?ctl c:RegulatingControl.enabled ?ctrlenabled.
          ?ctl c:RegulatingControl.mode ?moderaw.
           bind(strafter(str(?moderaw),"RegulatingControlModeKind.") as ?mode)
          ?ctl c:RegulatingControl.monitoredPhase ?monraw.
           bind(strafter(str(?monraw),"PhaseCode.") as ?monphs)
          ?ctl c:RegulatingControl.targetDeadband ?deadband.
          ?ctl c:RegulatingControl.targetValue ?setpoint.
          ?s c:ShuntCompensator.aVRDelay ?delay.
          ?ctl c:RegulatingControl.Terminal ?trm.
          ?trm c:Terminal.ConductingEquipment ?eq.
          ?eq a ?classraw.
           bind(strafter(str(?classraw),"CIM100#") as ?monclass)
          ?eq c:IdentifiedObject.name ?moneq.
          ?trm c:Terminal.ConnectivityNode ?moncn.
          ?moncn c:IdentifiedObject.name ?monbus.
          }
 ?s c:IdentifiedObject.mRID ?id. 
 ?t c:Terminal.ConductingEquipment ?s.
 ?t c:Terminal.ConnectivityNode ?cn. 
 ?cn c:IdentifiedObject.name ?bus
}
ORDER by ?name
    """ % mrid
    results = gridappsd_obj.query_data(query)
    capacitors = []
    results_obj = results['data']
    for p in results_obj['results']['bindings']:
        capacitors.append(p['id']['value'])
    return capacitors


def _main():
    _log.debug("Starting application")
    print("Application starting!!!-------------------------------------------------------")
    global message_period
    parser = argparse.ArgumentParser()
    parser.add_argument("simulation_id",
                        help="Simulation id to use for responses on the message bus.")
    parser.add_argument("request",
                        help="Simulation Request")
    parser.add_argument("--message_period",
                        help="How often the sample app will send open/close capacitor message.",
                        default=DEFAULT_MESSAGE_PERIOD)
    # These are now set through the docker container interface via env variables or defaulted to
    # proper values.
    #
    # parser.add_argument("-u", "--user", default="system",
    #                     help="The username to authenticate with the message bus.")
    # parser.add_argument("-p", "--password", default="manager",
    #                     help="The password to authenticate with the message bus.")
    # parser.add_argument("-a", "--address", default="127.0.0.1",
    #                     help="tcp address of the mesage bus.")
    # parser.add_argument("--port", default=61613, type=int,
    #                     help="the stomp port on the message bus.")
    #
    opts = parser.parse_args()
    listening_to_topic = simulation_output_topic(opts.simulation_id)
    message_period = int(opts.message_period)
    sim_request = json.loads(opts.request.replace("\'",""))
    model_mrid = sim_request["power_system_config"]["Line_name"]
    _log.debug("Model mrid is: {}".format(model_mrid))
    gapps = GridAPPSD(opts.simulation_id)
    capacitors = get_capacitor_mrids(gapps, model_mrid)
    toggler = CapacitorToggler(opts.simulation_id, gapps, capacitors)
    gapps.subscribe(listening_to_topic, toggler)
    while True:
        time.sleep(0.1)


if __name__ == "__main__":
    _main()
