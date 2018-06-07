'''
Author : Woonwon Lee, Jungdae Kim, Kyushik Min
Data : 2018.03.12, 2018.03.28, 2018.05.11, 2018.06.04
Project : Make your own Alpha Zero
Objective : find the problem of code. Let's Debugging!!
'''
from utils import render_str, get_state_pt, get_action, valid_actions
from neural_net import PVNet
import numpy as np
from collections import deque
import torch
import torch.optim as optim
from torch.nn import functional as F
from torch.autograd import Variable
from torch.utils.data import DataLoader
from agent import Player
import datetime

import sys
sys.path.append("env/")
import env_small as game
from evaluator import Evaluator

STATE_SIZE = 9
N_BLOCKS = 3
IN_PLANES = 5  # history * 2 + 1
OUT_PLANES = 64
BATCH_SIZE = 32
TOTAL_ITER = 100000
N_MCTS = 400
TAU_THRES = 8
N_EPISODES = 300
N_EPOCHS = 10
SAVE_CYCLE = 1000
LR = 2e-4
L2 = 1e-4
N_MATCH = 30
beta = 0.001


def self_play(n_episodes):
    agent.model.eval()
    print('self play for {} games'.format(n_episodes))
    for episode in range(n_episodes):
        # if (episode + 1)%100 == 0:
        #     print('playing {}th episode by self-play'.format(episode + 1))
        env = game.GameState('text')
        board = np.zeros([STATE_SIZE, STATE_SIZE])
        samples_black = []
        samples_white = []
        turn = 0
        root_id = (0,)
        win_index = 0
        step = 0
        action_index = None

        while win_index == 0:
            # render_str(board, STATE_SIZE, action_index)

            # ====================== start mcts ============================
            # pi = agent.get_pi(board, turn)
            # print('\nPi:')
            # print(pi.reshape(STATE_SIZE, STATE_SIZE).round(decimals=2))
            # ===================== collect samples ========================
            state = get_state_pt(root_id, STATE_SIZE, IN_PLANES)
            state_input = Variable(Tensor([state]))

            # ====================== print evaluation ======================
            p, v = agent.model(state_input)

            '''
            print(
                "\nProbability:\n{}".format(
                    p.data.cpu().numpy()[0].reshape(
                        STATE_SIZE, STATE_SIZE).round(decimals=2)))

            if turn == 0:
                print("\nBlack's winrate: {:.2f}%".format(
                    (v.data[0].numpy()[0] + 1) / 2 * 100))
            else:
                print("\nWhite's winrate: {:.2f}%".format(
                    100 - ((v.data[0].numpy()[0] + 1) / 2 * 100)))
            '''
            # ======================== get action ==========================
            p = p.data[0].cpu().numpy()
            action, action_index = get_action(p, board)
            # turn = 0(흑), 1(백)
            if turn == 0:
                samples_black.append((state, action))
            else:
                samples_white.append((state, action))
            root_id += (action_index,)
            # =========================== step =============================
            board, check_valid_pos, win_index, turn, _ = env.step(action)
            step += 1

            # used for debugging
            if not check_valid_pos:
                raise ValueError("no legal move!")

            if win_index != 0:
                if win_index == 1:
                    reward_black = 1.
                    reward_white = -1.
                    # win_color = 'Black'
                elif win_index == 2:
                    reward_black = -1.
                    reward_white = 1.
                    # win_color = 'White'
                else:
                    reward_black = 0.
                    reward_white = 0.
                    # win_color = 'None'

                # render_str(board, STATE_SIZE, action_index)
                # print("{} win in episode {}".format(win_color, episode + 1))
            # ====================== store in memory =======================
                for i in range(len(samples_black)):
                    memory.append((samples_black[i][0], samples_black[i][1],
                                   reward_black))
                for i in range(len(samples_white)):
                    memory.append((samples_white[i][0], samples_white[i][1],
                                   reward_white))
                agent.reset()


def train(n_game, n_epochs):
    agent.model.train()
    print('memory size:', len(memory))
    print('learning rate:', LR)

    dataloader = DataLoader(memory,
                            batch_size=BATCH_SIZE,
                            shuffle=True,
                            drop_last=True,
                            pin_memory=use_cuda)

    # use SGD + momentum optimizer according to the alphago zero paper
    optimizer = optim.SGD(agent.model.parameters(),
                          lr=LR,
                          momentum=0.9,
                          weight_decay=L2)

    loss_list = []

    for epoch in range(n_epochs):
        running_loss = 0.
        entropy = 0.
        step = 0
        for i, (s, a, z) in enumerate(dataloader):
            if use_cuda:
                s_batch = Variable(s.float()).cuda()
                a_batch = Variable(a.float()).cuda()
                z_batch = Variable(z.float()).cuda()
            else:
                s_batch = Variable(s.float())
                a_batch = Variable(a.float())
                z_batch = Variable(z.float())

            p_batch, v_batch = agent.model(s_batch)
            v_batch = v_batch.view(v_batch.size(0))
            loss_v = F.mse_loss(v_batch, z_batch)

            p_action = a_batch * p_batch
            p_action = torch.sum(p_action, 1)
            loss_p = torch.mean(
                torch.mul(-z_batch, torch.log(p_action + 1e-5)))
            entropy_p = torch.mean(
                torch.mul(-p_batch, torch.log(p_batch + 1e-5)))

            loss = loss_v + loss_p - beta * entropy_p
            loss_list.append(loss.data[0])

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            running_loss += loss_v.data[0]
            entropy += entropy_p.data[0]
            step += 1

        # loss for the value head
        print('{:3} epoch loss: {:.3f}'.format(
            epoch + 1, running_loss / step))
        # entropy of current policy
        print('{:3} epoch policy entropy: {:.3f}'.format(
            epoch + 1, entropy / step))

    torch.save(
        agent.model.state_dict(),
        './models/model_{}.pickle'.format(n_game))


def eval_model(player_model_path, enemy_model_path):
    evaluator = Evaluator(player_model_path, enemy_model_path)

    env = game.GameState('text')
    result = {'Player': 0, 'Enemy': 0, 'Draw': 0}
    turn = 0
    enemy_turn = 1
    player_elo = 1500
    enemy_elo = 1500
    print('Player ELO: {:.0f}, Enemy ELO: {:.0f}'.format(
        player_elo, enemy_elo))

    for i in range(N_MATCH):
        board = np.zeros([STATE_SIZE, STATE_SIZE])
        root_id = (0,)
        evaluator.player.root_id = root_id
        evaluator.enemy.root_id = root_id
        win_index = 0
        action_index = None
        '''
        if i % 2 == 0:
            print("Player Color: Black")
        else:
            print("Player Color: White")
        '''
        while win_index == 0:
            # render_str(board, STATE_SIZE, action_index)
            action, action_index = evaluator.get_action(
                root_id, board, turn, enemy_turn)

            if turn != enemy_turn:
                # print("player turn")
                root_id = evaluator.player.root_id + (action_index,)
                evaluator.enemy.root_id = root_id
            else:
                # print("enemy turn")
                root_id = evaluator.enemy.root_id + (action_index,)
                evaluator.player.root_id = root_id

            board, check_valid_pos, win_index, turn, _ = env.step(action)

            # used for debugging
            if not check_valid_pos:
                print('action:', action)
                print('board:', board)
                raise ValueError("no legal move!")

            # episode end
            if win_index != 0:
                if turn == enemy_turn:
                    if win_index == 3:
                        result['Draw'] += 1
                        # print("\nDraw!")

                        elo_diff = enemy_elo - player_elo
                        ex_pw = 1 / (1 + 10**(elo_diff / 400))
                        ex_ew = 1 / (1 + 10**(-elo_diff / 400))
                        player_elo += 32 * (0.5 - ex_pw)
                        enemy_elo += 32 * (0.5 - ex_ew)

                    else:
                        result['Player'] += 1
                        # print("\nPlayer Win!")

                        elo_diff = enemy_elo - player_elo
                        ex_pw = 1 / (1 + 10**(elo_diff / 400))
                        ex_ew = 1 / (1 + 10**(-elo_diff / 400))
                        player_elo += 32 * (1 - ex_pw)
                        enemy_elo += 32 * (0 - ex_ew)
                else:
                    if win_index == 3:
                        result['Draw'] += 1
                        # print("\nDraw!")

                        elo_diff = enemy_elo - player_elo
                        ex_pw = 1 / (1 + 10**(elo_diff / 400))
                        ex_ew = 1 / (1 + 10**(-elo_diff / 400))
                        player_elo += 32 * (0.5 - ex_pw)
                        enemy_elo += 32 * (0.5 - ex_ew)
                    else:
                        result['Enemy'] += 1
                        # print("\nEnemy Win!")

                        elo_diff = enemy_elo - player_elo
                        ex_pw = 1 / (1 + 10**(elo_diff / 400))
                        ex_ew = 1 / (1 + 10**(-elo_diff / 400))
                        player_elo += 32 * (0 - ex_pw)
                        enemy_elo += 32 * (1 - ex_ew)

                # Change turn
                enemy_turn = abs(enemy_turn - 1)
                turn = 0

                # render_str(board, STATE_SIZE, action_index)

                pw, ew, dr = result['Player'], result['Enemy'], result['Draw']
                winrate = (pw + 0.5 * dr) / (pw + ew + dr) * 100
                '''
                print('')
                print('=' * 20, " {}  Game End  ".format(i + 1), '=' * 20)
                print('Player Win: {}  Enemy Win: {}  Draw: {}  Winrate: {:.2f}%'.format(
                    pw, ew, dr, winrate))
                print('Player ELO: {:.0f}, Enemy ELO: {:.0f}'.format(
                    player_elo, enemy_elo))
                
                '''
                evaluator.reset()
    winrate = (pw + 0.5 * dr) / (pw + ew + dr) * 100
    print('winrate:', winrate)
    return winrate


if __name__ == '__main__':
    np.set_printoptions(suppress=True)
    np.random.seed(0)
    torch.manual_seed(0)
    # torch.cuda.manual_seed_all(0)
    use_cuda = torch.cuda.is_available()
    print('cuda:', use_cuda)
    Tensor = torch.cuda.FloatTensor if use_cuda else torch.FloatTensor

    memory = deque(maxlen=50000)
    agent = Player(STATE_SIZE, N_MCTS, IN_PLANES)
    agent.model = PVNet(IN_PLANES, STATE_SIZE)
    best_model_path = "./models/model_18.pickle"

    datetime_now = str(datetime.date.today()) + '_' + \
        str(datetime.datetime.now().hour) + '_' + \
        str(datetime.datetime.now().minute)

    if use_cuda:
        agent.model.cuda()

    for i in range(19, TOTAL_ITER):
        print('-----------------------------------------')
        print('{}th training process'.format(i + 1))
        print('-----------------------------------------')

        if i > 0:
            if best_model_path == 'random':
                agent.model = PVNet(IN_PLANES, STATE_SIZE)
                print('make new agent')
            else:
                agent.model.load_state_dict(torch.load(best_model_path))
                print('load model from ' + best_model_path)
        self_play(N_EPISODES)
        train(i, N_EPOCHS)

        player_model_path = "./models/model_{}.pickle".format(i)
        if i == 0:
            best_model_path = 'random'

        winrate = eval_model(player_model_path, best_model_path)
        if winrate > 50:
            best_model_path = player_model_path

        memory = deque(maxlen=50000)
        '''
        if (i + 1) >= 160:
            train(i, N_EPOCHS)

        if (i + 1) % SAVE_CYCLE == 0:
            torch.save(
                agent.model.state_dict(),
                './models/{}_{}_step_model.pickle'.format(datetime_now, STEPS))

        '''