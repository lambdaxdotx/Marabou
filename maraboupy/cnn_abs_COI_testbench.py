import sys
import os
import tensorflow as tf
import numpy as np
import keras2onnx
import onnx
import onnxruntime
from cnn_abs import *
import logging
import time
import argparse
import datetime
import json

#from itertools import product, chain
from maraboupy import MarabouNetworkONNX as monnx
from tensorflow.keras import datasets, layers, models
from tensorflow.keras.models import load_model
import matplotlib.pyplot as plt

###########################################################################
####  _____              __ _                   _   _                  ####
#### /  __ \            / _(_)                 | | (_)                 ####
#### | /  \/ ___  _ __ | |_ _  __ _ _   _  __ _| |_ _  ___  _ __  ___  ####
#### | |    / _ \| '_ \|  _| |/ _` | | | |/ _` | __| |/ _ \| '_ \/ __| ####
#### | \__/\ (_) | | | | | | | (_| | |_| | (_| | |_| | (_) | | | \__ \ ####
####  \____/\___/|_| |_|_| |_|\__, |\__,_|\__,_|\__|_|\___/|_| |_|___/ ####
####                           __/ |                                   ####
####                          |___/                                    ####
###########################################################################

tf.compat.v1.enable_v2_behavior()

def dumpJson(jsonDict):
    if cfg_dumpQueries:
        return
    with open("Results.json", "w") as f:
        json.dump(jsonDict, f, indent = 4)

def subResultAppend(resultsJson, runType=None, index=None, numMasks=None, runtime=None, runtimeTotal=None, originalQueryStats=None, finalQueryStats=None, sat=None, timedOut=None):
    resultsJson["subResults"].append({"type": runType,
                                      "index" : index,
                                      "outOf" : numMasks,
                                      "runtime" : runtime,
                                      "runtimeTotal":runtimeTotal,
                                      "originalQueryStats" : originalQueryStats,
                                      "finalQueryStats" : finalQueryStats,
                                      "SAT" : sat,
                                      "timedOut" : timedOut})
    dumpJson(resultsJson)

def subResultUpdate(resultsJson, runType=None, index=None, numMasks=None, runtime=None, runtimeTotal=None, originalQueryStats=None, finalQueryStats=None, sat=None, timedOut=None):
    resultsJson["subResults"][-1] = {"type": runType,
                                     "index" : index,
                                     "outOf" : numMasks,
                                     "runtime" : runtime,
                                     "runtimeTotal":runtimeTotal,
                                     "originalQueryStats" : originalQueryStats,
                                     "finalQueryStats" : finalQueryStats,
                                     "SAT" : sat,
                                     "timedOut" : timedOut}
    dumpJson(resultsJson)

defaultBatchId = "default_" + datetime.datetime.now().strftime("%d-%m-%y_%H-%M-%S")
parser = argparse.ArgumentParser(description='Run MNIST based verification scheme using abstraction')
parser.add_argument("--no_coi",         action="store_true",                        default=False,                  help="Don't use COI pruning")
parser.add_argument("--no_mask",        action="store_true",                        default=False,                  help="Don't use mask abstraction")
parser.add_argument("--no_full",        action="store_true",                        default=False,                  help="Don't run on full network")
parser.add_argument("--no_verify",      action="store_true",                        default=False,                  help="Don't run verification process")
parser.add_argument("--dump_queries",   action="store_true",                        default=False,                  help="Don't solve queries, just create and dump them")
parser.add_argument("--use_dumped_queries", action="store_true",                    default=False,                  help="Use dumped queries")
parser.add_argument("--dump_dir",       type=str,                                   default="",                     help="Location of dumped queries")
parser.add_argument("--fresh",          action="store_true",                        default=False,                  help="Retrain CNN")
parser.add_argument("--validation", action="store_true",                    default=False,                  help="Use the validation DNN")
parser.add_argument("--cnn_size",       type=str, choices=["big","medium","small","toy"], default="small",          help="Which CNN size to use")
parser.add_argument("--run_on",         type=str, choices=["local", "cluster"],     default="local",                help="Is the program running on cluster or local run?")
parser.add_argument("--run_title",      type=str,                                   default="default",              help="Add unique identifier identifying this current run")
parser.add_argument("--batch_id",       type=str,                                   default=defaultBatchId,         help="Add unique identifier identifying the whole batch")
parser.add_argument("--prop_distance",  type=float,                                 default=0.1,                    help="Distance checked for adversarial robustness (L1 metric)")
parser.add_argument("--prop_slack",     type=float,                                 default=0,                      help="Slack given at the output property, ysecond >= ymax - slack. Positive slack makes the property easier to satisfy, negative makes it harder.")
parser.add_argument("--num_cpu",        type=int,                                   default=8,                      help="Number of CPU workers in a cluster run.")
parser.add_argument("--timeout",        type=int,                                   default=1200,                   help="Solver timeout in seconds.")
#parser.add_argument("--timeout_factor", type=float,                                 default=1.5,                   help="timeoutFactor in DNC mode.")
parser.add_argument("--sample",         type=int,                                   default=0,                      help="Index, in MNIST database, of sample image to run on.")
parser.add_argument("--policy",         type=str, choices=mnistProp.policies,       default="AllClassRank",         help="Which abstraction policy to use")
parser.add_argument("--sporious_strict",action="store_true",                        default=True,                  help="Criteria for sporious is that the original label is not achieved (no flag) or the second label is actually voted more tha the original (flag)")
parser.add_argument("--double_check"   ,action="store_true",                        default=False,                  help="Run Marabou again using recieved CEX as an input assumption.")
parser.add_argument("--bound_tightening",         type=str, choices=["lp", "lp-inc", "milp", "milp-inc", "iter-prop", "none"], default="none", help="Which bound tightening technique to use.")
parser.add_argument("--symbolic",       type=str, choices=["deeppoly", "sbt", "none"], default="deeppoly",              help="Which bound tightening technique to use.")
parser.add_argument("--solve_with_milp",action="store_true",                        default=False,                  help="Use MILP solver instead of regular engine.")
parser.add_argument("--abs_layer",      type=str, default="c2",              help="Which layer should be abstracted.")
parser.add_argument("--arg",  type=str, default="", help="Push custom string argument.")
parser.add_argument("--no_dumpBounds",action="store_true",                        default=False,                  help="Disable initial bound tightening.")
args = parser.parse_args()

resultsJson = dict()
cfg_freshModelOrig    = args.fresh
cfg_noVerify          = args.no_verify
cfg_pruneCOI          = not args.no_coi
cfg_maskAbstract      = not args.no_mask
cfg_runFull           = not args.no_full
cfg_propDist          = args.prop_distance
cfg_propSlack         = args.prop_slack
cfg_runOn             = args.run_on
cfg_runTitle          = args.run_title
cfg_batchDir          = args.batch_id if "batch_" + args.batch_id else ""
cfg_numClusterCPUs    = args.num_cpu
cfg_abstractionPolicy = args.policy
cfg_sporiousStrict    = args.sporious_strict
cfg_sampleIndex       = args.sample
cfg_doubleCheck       = args.double_check
cfg_boundTightening   = args.bound_tightening
cfg_solveWithMILP     = args.solve_with_milp
cfg_symbolicTightening= args.symbolic
cfg_timeoutInSeconds  = args.timeout
cfg_dumpQueries       = args.dump_queries
cfg_useDumpedQueries  = args.use_dumped_queries
cfg_dumpDir           = args.dump_dir
cfg_validation        = args.validation
cfg_cnnSizeChoice     = args.cnn_size + ("" if not cfg_validation else "_validation")
#cfg_dumpBounds        = cfg_maskAbstract or (cfg_boundTightening != "none")
cfg_dumpBounds        = not args.no_dumpBounds
cfg_absLayer          = args.abs_layer
cfg_extraArg          = args.arg

resultsJson["cfg_freshModelOrig"]    = cfg_freshModelOrig
resultsJson["cfg_noVerify"]          = cfg_noVerify
resultsJson["cfg_cnnSizeChoice"]     = cfg_cnnSizeChoice
resultsJson["cfg_pruneCOI"]          = cfg_pruneCOI
resultsJson["cfg_maskAbstract"]      = cfg_maskAbstract
resultsJson["cfg_propDist"]          = cfg_propDist
resultsJson["cfg_propSlack"]         = cfg_propSlack
resultsJson["cfg_runOn"]             = cfg_runOn
resultsJson["cfg_runTitle"]          = cfg_runTitle
resultsJson["cfg_batchDir"]          = cfg_batchDir
resultsJson["cfg_numClusterCPUs"]    = cfg_numClusterCPUs
resultsJson["cfg_abstractionPolicy"] = cfg_abstractionPolicy
resultsJson["cfg_sporiousStrict"]    = cfg_sporiousStrict
resultsJson["cfg_sampleIndex"]       = cfg_sampleIndex
resultsJson["cfg_doubleCheck"]       = cfg_doubleCheck
resultsJson["cfg_boundTightening"]   = cfg_boundTightening
resultsJson["cfg_solveWithMILP"]     = cfg_solveWithMILP
resultsJson["cfg_symbolicTightening"]= cfg_symbolicTightening
resultsJson["cfg_timeoutInSeconds"]  = cfg_timeoutInSeconds
resultsJson["cfg_dumpQueries"]       = cfg_dumpQueries
resultsJson["cfg_useDumpedQueries"]  = cfg_useDumpedQueries
resultsJson["cfg_dumpDir"]           = cfg_dumpDir
resultsJson["cfg_validation"]        = cfg_validation
resultsJson["cfg_dumpBounds"]        = cfg_dumpBounds
resultsJson["cfg_extraArg"]          = cfg_extraArg

resultsJson["SAT"] = None
resultsJson["Result"] = "TIMEOUT"
resultsJson["subResults"] = []

cexFromImage = False

#mnistProp.runTitle = cfg_runTitle
mnistProp.dumpDir = cfg_dumpDir

optionsLocal   = Marabou.createOptions(snc=False, verbosity=2,                                solveWithMILP=cfg_solveWithMILP, timeoutInSeconds=cfg_timeoutInSeconds, milpTightening=cfg_boundTightening, dumpBounds=cfg_dumpBounds, tighteningStrategy=cfg_symbolicTightening)
optionsCluster = Marabou.createOptions(snc=True,  verbosity=0, numWorkers=cfg_numClusterCPUs, solveWithMILP=cfg_solveWithMILP, timeoutInSeconds=cfg_timeoutInSeconds, milpTightening=cfg_boundTightening, dumpBounds=cfg_dumpBounds, tighteningStrategy=cfg_symbolicTightening)
if cfg_runOn == "local":
    mnistProp.optionsObj = optionsLocal
else :
    mnistProp.optionsObj = optionsCluster

mnistProp.basePath = "/cs/labs/guykatz/matanos/Marabou/maraboupy"
currPath = mnistProp.basePath + "/logs"
if not os.path.exists(currPath):
    os.mkdir(currPath)
if cfg_batchDir:
    currPath += "/" + cfg_batchDir
    if not os.path.exists(currPath):
        os.mkdir(currPath)
if cfg_runTitle:
    currPath += "/" + cfg_runTitle
    if not os.path.exists(currPath):
        os.mkdir(currPath)        
os.chdir(currPath)
mnistProp.currPath = currPath
logging.basicConfig(level = logging.DEBUG, format = "%(asctime)s %(levelname)s %(message)s", filename = "cnnAbsTB.log", filemode = "w")
mnistProp.logger = logging.getLogger('cnnAbsTB_{}'.format(cfg_runTitle))
#logger.setLevel(logging.DEBUG)
mnistProp.logger.setLevel(logging.INFO)
fh = logging.FileHandler('cnnAbsTB_{}.log'.format(cfg_runTitle))
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
mnistProp.logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
mnistProp.logger.addHandler(ch)

logging.getLogger('matplotlib.font_manager').disabled = True

dumpJson(resultsJson)

###############################################################################
#### ______                                ___  ___          _      _      ####
#### | ___ \                               |  \/  |         | |    | |     ####
#### | |_/ / __ ___ _ __   __ _ _ __ ___   | .  . | ___   __| | ___| |___  ####
#### |  __/ '__/ _ \ '_ \ / _` | '__/ _ \  | |\/| |/ _ \ / _` |/ _ \ / __| ####
#### | |  | | |  __/ |_) | (_| | | |  __/  | |  | | (_) | (_| |  __/ \__ \ ####
#### \_|  |_|  \___| .__/ \__,_|_|  \___|  \_|  |_/\___/ \__,_|\___|_|___/ ####
####               | |                                                     ####
####               |_|                                                     ####
###############################################################################

replaceLayerName = cfg_absLayer

## Build initial model.

printLog("Started model building")
modelOrig = genCnnForAbsTest(cfg_freshModelOrig=cfg_freshModelOrig, cnnSizeChoice=cfg_cnnSizeChoice)
maskShape = modelOrig.get_layer(name=replaceLayerName).output_shape[:-1]
if maskShape[0] == None:
    maskShape = maskShape[1:]

modelOrigDense = cloneAndMaskConvModel(modelOrig, replaceLayerName, np.ones(maskShape))
#FIXME - created modelOrigDense to compensate on possible translation error when densifing. This way the abstractions are assured to be abstraction of this model.
#compareModels(modelOrig, modelOrigDense)

mnistProp.origMSize = cfg_cnnSizeChoice
mnistProp.origMDense = modelOrigDense
printLog("Finished model building")

if cfg_noVerify:
    printLog("Skipping verification phase")
    exit(0)

#############################################################################################
####  _   _           _  __ _           _   _               ______ _                     ####
#### | | | |         (_)/ _(_)         | | (_)              | ___ \ |                    ####
#### | | | | ___ _ __ _| |_ _  ___ __ _| |_ _  ___  _ __    | |_/ / |__   __ _ ___  ___  ####
#### | | | |/ _ \ '__| |  _| |/ __/ _` | __| |/ _ \| '_ \   |  __/| '_ \ / _` / __|/ _ \ ####
#### \ \_/ /  __/ |  | | | | | (_| (_| | |_| | (_) | | | |  | |   | | | | (_| \__ \  __/ ####
####  \___/ \___|_|  |_|_| |_|\___\__,_|\__|_|\___/|_| |_|  \_|   |_| |_|\__,_|___/\___| ####
####                                                                                     ####
#############################################################################################

## Choose adversarial example

printLog("Choosing adversarial example")

xAdv = mnistProp.x_test[cfg_sampleIndex]
yAdv = mnistProp.y_test[cfg_sampleIndex]
yPredict = modelOrigDense.predict(np.array([xAdv]))
yMax = yPredict.argmax()
yPredictNoMax = np.copy(yPredict)
yPredictNoMax[0][yMax] = np.min(yPredict)
ySecond = yPredictNoMax.argmax()
if ySecond == yMax:
    ySecond = 0 if yMax > 0 else 1

fName = "xAdv.png"
printLog("Printing original input to file {}, this is sample {} with label {}".format(fName, cfg_sampleIndex, yAdv))
plt.figure()
plt.imshow(np.squeeze(xAdv))
plt.title('Example %d. Label: %d' % (cfg_sampleIndex, yAdv))
plt.savefig(fName)

resultsJson["yDataset"] = int(yAdv.item())
resultsJson["yMaxPrediction"] = int(yMax)
resultsJson["ySecondPrediction"] = int(ySecond)
dumpJson(resultsJson)


if cfg_dumpBounds:
    printLog("Started dumping bounds - used for abstraction")
    ipq = dumpBounds(modelOrigDense, xAdv, cfg_propDist, cfg_propSlack, yMax, ySecond)
    printLog("Finished dumping bounds - used for abstraction")
    print(ipq.getNumberOfVariables())
    if ipq.getNumberOfVariables() == 0:
        resultsJson["SAT"] = False
        resultsJson["Result"] = "UNSAT"
        dumpJson(resultsJson)
        printLog("UNSAT on first LP bound tightening")
        exit()
if os.path.isfile(os.getcwd() + "/dumpBounds.json") and cfg_dumpBounds:
    with open('dumpBounds.json', 'r') as boundFile:
        boundList = json.load(boundFile)
        boundDict = {bound["variable"] : (bound["lower"], bound["upper"]) for bound in boundList}
else:
    boundDict = None

maskList = list(genActivationMask(intermidModel(modelOrigDense, replaceLayerName), xAdv, yMax, policy=cfg_abstractionPolicy, boundDict=boundDict
))
if not cfg_maskAbstract:
    maskList = []
printLog("Created {} masks".format(len(maskList)))
#for i,mask in enumerate(maskList):
#    print("mask,{}=\n{}".format(i,mask))
#exit()

#with open(mnistProp.basePath + "/" + cfg_extraArg, "rb") as f:             DEBUG SPORIOUS CEX
#    cex = np.load(f, allow_pickle=True)
#print(modelOrigDense.predict(np.array([cex])))
#print(modelOrigDense.predict(np.array([cex])).argmax())
#print(isCEXSporious(modelOrigDense, xAdv, 0.05, 0, yMax, ySecond, cex, sporiousStrict=True))
#exit()

printLog("Strating verification phase")

reachedFull = False
successful = None
reachedFinal = False
startTotal = time.time()
sat = None
timedOut = None

#modelOrigDenseSavedName = mnistProp.basePath + "/" + "modelOrigDense.h5"
modelOrigDenseSavedName = "modelOrigDense.h5"
modelOrigDense.save(modelOrigDenseSavedName)
