#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) and accountant(mod 17) can update fee balances
		if ($id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/fee_update.cgi">Update Fee Balance</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to update fee balances.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Update Student Balance</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/fee_update.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/fee_update.cgi">/login.html?cont=/cgi-bin/fee_update.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/fee_update.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

PM: {
if ( $post_mode ) {

	unless ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and $auth_params{"confirm_code"} eq $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid request.</span> Do not alter the hidden values in the HTML form.!;
		$post_mode = 0;
		last PM; 
	}

	my $adm_filtered = 0;
	my %adms = ();	

	if (exists $auth_params{"adm_nos"} and length($auth_params{"adm_nos"}) > 0) {
		
		my @possib_adms = split/\s+/,$auth_params{"adm_nos"};

		for my $possib_adm (@possib_adms) {

			if ($possib_adm =~ /^\d+$/) {
				$adms{$possib_adm} = {};
				$adm_filtered++;
			}

			#ranges
			elsif ($possib_adm =~ /^(\d+)\-(\d+)$/) {
				my $start = $1;
				my $stop = $2;
				
				#be kind to users, swap start 
				#and stop if reverse-ordered
				if ( $start > $stop ) {	
					my $tmp = $start;
					$start = $stop;
					$stop = $tmp;
				}

				for ( my $i = $start; $i <= $stop; $i++ ) {
					$adms{$i} = {};
					$adm_filtered++;	
				}
			}
		}

		#read 'adms' table to determine student rolls
		my %rolls = ();
		my $prep_stmt3 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE adm_no=? LIMIT 1");

		if ($prep_stmt3) {

			for my $adm (keys %adms) {

				my $rc = $prep_stmt3->execute($adm);

				if ($rc) {
					while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
						${$adms{$rslts[0]}}{"roll"} = $rslts[1];
						$rolls{$rslts[1]} = "N/A";		
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM adms statement: ", $prep_stmt3->errstr, $/;
				}
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM adms statement: ", $prep_stmt3->errstr, $/;
		}

		for my $adm (keys %adms) {
			delete $adms{$adm} if (not exists ${$adms{$adm}}{"roll"});
		}

		#read 'student_rolls' to derermine classes
		if ( scalar (keys %rolls) > 0 ) {

			my %roll_students_lookup = ();
			my $yr = (localtime)[5] + 1900;

			my @where_clause_bts = ();
	
			for my $roll (keys %rolls) {
				push @where_clause_bts, "table_name=?";
			}

			my $where_clause = join(" OR ", @where_clause_bts);

			my $prep_stmt4 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls WHERE $where_clause");

			if ($prep_stmt4) {
				my $rc = $prep_stmt4->execute(keys %rolls);
				if ($rc) {
					while ( my @rslts = $prep_stmt4->fetchrow_array() ) {	
						my $class = "N/A";
						#student ha already graduated
						if ( $rslts[3] < $yr ) {

							my $study_yr = ($rslts[3] - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;

							$class .= "($rslts[3])";	
						}
						else {
							my $study_yr = ($yr - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;	
						}

						$rolls{$rslts[0]} = $class;	
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt4->errstr, $/;
			}

			for my $adm ( keys %adms ) {

				my $roll = ${$adms{$adm}}{"roll"};
				my $class = "N/A";

				#accomodate missing classes
				if ( exists $rolls{$roll} ) {
					$class = $rolls{$roll};
				}

				${$adms{$adm}}{"class"} = $class;
				${$roll_students_lookup{$roll}}{$adm}++;
			}

			for my $roll ( keys %rolls ) {

				my @roll_students =  keys %{$roll_students_lookup{$roll}};
				my $num_roll_students = scalar(@roll_students);

				my @where_clause_bts = ();
	
				foreach ( @roll_students ) {
					push @where_clause_bts, "adm=?";
				}

				my $where_clause = join(" OR ", @where_clause_bts);

				my $prep_stmt5 = $con->prepare("SELECT adm,s_name,o_names,house_dorm FROM `$roll` WHERE $where_clause LIMIT $num_roll_students");

				if ( $prep_stmt5 ) {

					my $rc = $prep_stmt5->execute(@roll_students);

					if ($rc) {
						while ( my @rslts = $prep_stmt5->fetchrow_array() ) {
							${$adms{$rslts[0]}}{"name"} = $rslts[1] . " " .$rslts[2];
							${$adms{$rslts[0]}}{"dorm"} = (not defined $rslts[3] or $rslts[3] eq "") ? "N/A" : $rslts[3];
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt5->errstr, $/;
				}

			}
		}
	}

	my $class_filtered = 0;
	my %classes;
	my %student_rolls = ();
	
	#don't do adm AND class lim
	if (not $adm_filtered) {

		my $yr = (localtime)[5] + 1900;
		if ( exists $auth_params{"year"} and $auth_params{"year"} =~ /^\d{4}$/ ) {
			#can't go forward in time
			if ($auth_params{"year"} <= $yr) {
				$yr = $auth_params{"year"};	
			}
		}

		for my $auth_param (keys %auth_params) {
			if ($auth_param =~ /^class_/) {
				$classes{uc($auth_params{$auth_param})}++;	
			}
		}

		#read student rolls
		if ( scalar(keys %classes) > 0 ) {
			$class_filtered++;

			my $current_yr = (localtime)[5] + 1900;

			my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls");
	
			if ($prep_stmt1) {
				my $rc = $prep_stmt1->execute();
				if ($rc) {
					while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

						my $class = "N/A";
						#student ha already graduated
						if ( $rslts[3] < $current_yr ) {

							my $study_yr = ($yr - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;

							if (exists $classes{$class}) {
								$student_rolls{$rslts[0]} = $class . "($rslts[3])" ;
							}
						}
						else {
							my $study_yr = ($yr - $rslts[2]) + 1;
							$class = uc($rslts[1]);
							$class =~ s/\d+/$study_yr/;	
							if (exists $classes{$class}) {
								$student_rolls{$rslts[0]} = $class;
							}
						}
					}
				}
				else {
					print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
			}
		}

		if ( scalar (keys %student_rolls) ) {
			for my $roll ( keys %student_rolls ) {

				my $class = $student_rolls{$roll};

				my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names,house_dorm FROM `$roll`");

				if ($prep_stmt2) {
					my $rc = $prep_stmt2->execute();
					if ($rc) {
						while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
							$adms{$rslts[0]} = {"class" => $class, "roll" => $roll, "name" => $rslts[1] . " " .$rslts[2], "dorm" => ((not defined $rslts[3] or $rslts[3] eq "") ? "N/A" : $rslts[3])};
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM $roll statement: ", $prep_stmt2->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM $roll statement: ", $prep_stmt2->errstr, $/;
				}
			}
		}
	}

	#no student matched
	unless ( scalar(keys %adms) > 0 ) {
		#an invalid selection was made
		if ($adm_filtered or $class_filtered) {
			$feedback = qq!<span style="color: red">Your student filter did not match any students in the database.</span>!;
		}
		else {
			$feedback = qq!<span style="color: red">You did not specify any student filter(admission number or class).</span>!;
		}
		$post_mode = 0;
		last PM;
	}


	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my %voteheads = ();
	for my $param (keys %auth_params) {
		if ($param =~ /votehead_(.+)/) {
			my $votehead = $1;
			if ($auth_params{$param} =~ /^[\+\-]?\d+$/) {
				$voteheads{$votehead} = $auth_params{$param};
			}
		}
	}

	#should have specified some 
	unless (scalar (keys %voteheads) > 0) {
		$feedback = qq!<span style="color: red">You did not specify the voteheads that you want to update.</span>!;
		$post_mode = 0;
		last PM;
	}

	my %pre_existing_accnts = ();
	my %new_accnts = ();
	my %cash_book_updates = ();
	my %payments_book_updates = ();
	my %prepayment_write_offs = ();

	my $time = time;
	my $encd_time = $cipher->encrypt(add_padding($time));

	my $prep_stmt7 = $con->prepare("SELECT account_name,class,amount,hmac FROM account_balances WHERE BINARY account_name=? LIMIT 1");
	
	if ($prep_stmt7) {

		#read current arrears first
		my %arrears = ();

		for my $votehead ("arrears", keys %voteheads) {

			for my $adm (keys %adms) {
	
				my $encd_accnt_name = $cipher->encrypt(add_padding($adm . "-" . $votehead));	

				my $rc = $prep_stmt7->execute($encd_accnt_name);

				if ($rc) {

					while (my @rslts = $prep_stmt7->fetchrow_array()) {

						my $decrypted_account_name = $cipher->decrypt($rslts[0]);
						my $decrypted_class = $cipher->decrypt($rslts[1]);
						my $decrypted_amount = $cipher->decrypt($rslts[2]);

						my $account_name = remove_padding($decrypted_account_name);
						my $class = remove_padding($decrypted_class);
						my $amount = remove_padding($decrypted_amount);

						#valid decryption
						if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

							my $hmac = uc(hmac_sha1_hex($account_name . $class . $amount, $key));

							#auth the data
							if ( $hmac eq $rslts[3] ) {

								if ($votehead eq "arrears") {
									$arrears{$adm} = $amount;
								}
								else {
									#if this' a +ve charge, check if the student
									#has arrears.
									#try & settle this charge from there 
									my $delta_amnt = $voteheads{$votehead};
									if ($delta_amnt > 0) {

										if ( exists $arrears{$adm} and $arrears{$adm} < 0) {
											#settle with surplus
											my $enc_cash_book_receipt_votehead = $cipher->encrypt(add_padding("Update($adm-$time)-$votehead"));
											my $enc_cash_book_votehead = $cipher->encrypt(add_padding($votehead));
											my $enc_cash_book_amount = "";
											my $cash_book_hmac = "";

											if ( ($arrears{$adm} * -1) > $delta_amnt ) {

												$prepayment_write_offs{$adm} += $delta_amnt;
												$arrears{$adm} += $delta_amnt;

												#this' income, enter it	
												$enc_cash_book_amount = $cipher->encrypt(add_padding($delta_amnt));
												$cash_book_hmac = uc(hmac_sha1_hex("Update($adm-$time)-$votehead" . $votehead . $delta_amnt . $time, $key));

												$delta_amnt = 0;
												#alter arrears
												#
											}
											else {
												$prepayment_write_offs{$adm} += $arrears{$adm};

												$delta_amnt += $arrears{$adm};

												#record income
												$enc_cash_book_amount = $cipher->encrypt(add_padding($arrears{$adm}));
												$cash_book_hmac = uc(hmac_sha1_hex("Update($adm-$time)-$votehead" . $votehead . $delta_amnt . $time, $key));

												$arrears{$adm} = 0;
											}

											#enter this as income
											$cash_book_updates{"Update($adm-$time)-$votehead"} = {"receipt_votehead" => $enc_cash_book_receipt_votehead, "votehead" => $enc_cash_book_votehead, "amount" => $enc_cash_book_amount, "time" => $encd_time, "hmac" => $cash_book_hmac};

											#add it to accounts to update	
											my $arrears_hmac = uc(hmac_sha1_hex("$adm-arrears" . $class . $arrears{$adm}, $key));
									
											my $enc_accnt = $cipher->encrypt(add_padding("$adm-arrears"));
											my $enc_amnt = $cipher->encrypt(add_padding($arrears{$adm}));
	
											$pre_existing_accnts{"$adm-arrears"} = {"account_name" => $enc_accnt, "class" => $rslts[1], "amount" => $enc_amnt, "hmac" => $arrears_hmac};
										}
									}

									else {
										#record this as an expense
										my $enc_payments_book_voucher_votehead = $cipher->encrypt(add_padding("Update($adm-$time)-$votehead"));
										my $enc_payments_book_votehead = $cipher->encrypt(add_padding($votehead));
										my $enc_payments_book_amount = $cipher->encrypt(add_padding($delta_amnt * -1));
										my $payments_book_hmac = uc(hmac_sha1_hex("Update($adm-$time)-$votehead" . $votehead . ($delta_amnt * -1) . $time, $key));
	
										$payments_book_updates{"Update($adm-$time)-$votehead"} = {"voucher_votehead" => $enc_payments_book_voucher_votehead, "votehead" => $enc_payments_book_votehead, "amount" => $enc_payments_book_amount, "time" => $encd_time, "hmac" => $payments_book_hmac};


										#adding this to the current balance will
										#result in a negative amount
										#throw the surplus to arrears
										if ( ($delta_amnt + $amount) < 0 ) {

											my $arrears = $delta_amnt + $amount;
											$delta_amnt = -1 * $amount;

											if ( exists ($arrears{$adm}) ) {
												$arrears += $arrears{$adm};
											}
											#had a bug here
											#the new arrears should now persist
											#so that the correctness of the 
											#code does not rely on the order
											#in which the voteheads are processed
											$arrears{$adm} = $arrears;

											#add it to accounts to update	
											my $arrears_hmac = uc(hmac_sha1_hex("$adm-arrears" . $class . $arrears, $key));
									
											my $enc_accnt = $cipher->encrypt(add_padding("$adm-arrears"));
											my $enc_amnt = $cipher->encrypt(add_padding($arrears));

											#pre-existing account
											if (exists $arrears{$adm}) {	
												$pre_existing_accnts{"$adm-arrears"} = {"account_name" => $enc_accnt, "class" => $rslts[1], "amount" => $enc_amnt, "hmac" => $arrears_hmac};
											}
											#new account
											else {	
												$new_accnts{"$adm-arrears"} = {"account_name" => $enc_accnt, "class" => $rslts[1], "amount" => $enc_amnt, "hmac" => $arrears_hmac};
											}
										}
									}

									#pre-exising, simply update	
									my $new_amount = $amount + $delta_amnt;
									my $enc_new_amount = $cipher->encrypt(add_padding($new_amount));

									my $new_hmac = uc(hmac_sha1_hex($adm . "-" . $votehead . $class . $new_amount, $key));
	
									$pre_existing_accnts{$adm . "-" . $votehead} = {"account_name" => $encd_accnt_name, "class" => $rslts[1], "amount" => $enc_new_amount, "hmac" => $new_hmac};

									#record this as 
								}
							}
						}
					}
				}
				else {
					print STDERR "Couldn't execute SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
				}
			}
			
			#already processed arrears, jump on.
			next if ($votehead eq "arrears");

			#acounts that I haven't seen
			for my $adm_2 (keys %adms) {
	
				if ( not exists $pre_existing_accnts{$adm_2 . "-" . $votehead} ) {

					my $delta_amnt = $voteheads{$votehead};

					if ($delta_amnt > 0) {

						if ( exists $arrears{$adm_2} and $arrears{$adm_2} < 0) {
							#settle with surplus
							if ( ($arrears{$adm_2} * -1) > $delta_amnt ) {

								$arrears{$adm_2} += $delta_amnt;
								$delta_amnt = 0;	
							}
							else {
								$delta_amnt += $arrears{$adm_2};
								$arrears{$adm_2} = 0;
							}

							#add it to accounts to update	
							my $arrears_hmac = uc(hmac_sha1_hex("$adm_2-arrears" . ${$adms{$adm_2}}{"roll"} . $arrears{$adm_2}, $key));
										
							my $enc_accnt = $cipher->encrypt(add_padding("$adm_2-arrears"));
							my $enc_class = $cipher->encrypt(add_padding(${$adms{$adm_2}}{"roll"}));
							my $enc_amnt = $cipher->encrypt(add_padding($arrears{$adm_2}));
	
							$pre_existing_accnts{"$adm_2-arrears"} = {"account_name" => $enc_accnt, "class" => $enc_class, "amount" => $enc_amnt, "hmac" => $arrears_hmac};
						}
					}

					else {

						#put all this money in arrears
						my $arrears = $delta_amnt;
						$delta_amnt = 0;

						if ( exists ($arrears{$adm_2}) ) {
							$arrears += $arrears{$adm_2};
						}

						#add it to accounts to update	
						my $arrears_hmac = uc(hmac_sha1_hex("$adm_2-arrears" . ${$adms{$adm_2}}{"roll"} . $arrears, $key));
									
						my $enc_accnt = $cipher->encrypt(add_padding("$adm_2-arrears"));
						my $enc_class = $cipher->encrypt(add_padding(${$adms{$adm_2}}{"roll"}));
						my $enc_amnt = $cipher->encrypt(add_padding($arrears));

						#pre-existing account
						if (exists $arrears{$adm_2}) {	
							$pre_existing_accnts{"$adm_2-arrears"} = {"account_name" => $enc_accnt, "class" => $enc_class, "amount" => $enc_amnt, "hmac" => $arrears_hmac};
						}
						#new account
						else {	
							$new_accnts{"$adm_2-arrears"} = {"account_name" => $enc_accnt, "class" => $enc_class, "amount" => $enc_amnt, "hmac" => $arrears_hmac};
						}
					}

					my $encd_accnt_name = $cipher->encrypt(add_padding($adm_2 . "-" . $votehead));
					my $encd_class = $cipher->encrypt(add_padding(${$adms{$adm_2}}{"roll"}));
					my $encd_amount = $cipher->encrypt(add_padding($delta_amnt));
					my $hmac =  uc(hmac_sha1_hex($adm_2 . "-" . $votehead . ${$adms{$adm_2}}{"roll"} . $delta_amnt , $key));	

					$new_accnts{"$adm_2-$votehead"} = {"account_name" => $encd_accnt_name, "class" => $encd_class, "amount" => $encd_amount, "hmac" => $hmac};

				}
			}
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM account_balances: ", $prep_stmt7->errstr, $/;
	}

	if (scalar (keys %new_accnts) > 0) {

		my $prep_stmt8 = $con->prepare("REPLACE INTO account_balances VALUES(?,?,?,?)");

		if ($prep_stmt8) {
			for my $accnt (keys %new_accnts) {
				my $rc = $prep_stmt8->execute(${$new_accnts{$accnt}}{"account_name"}, ${$new_accnts{$accnt}}{"class"}, ${$new_accnts{$accnt}}{"amount"}, ${$new_accnts{$accnt}}{"hmac"});
				unless ($rc) {
					print STDERR "Couldn't execute REPLACE INTO account_balances: ", $prep_stmt8->errstr, $/;
				}
			}
		}
		else {
			print STDERR "Couldn't prepare REPLACE INTO account_balances: ", $prep_stmt8->errstr, $/;
		}
	}
	if ( scalar(keys %pre_existing_accnts) > 0 ) {

		my $prep_stmt9 = $con->prepare("UPDATE account_balances SET amount=?, hmac=? WHERE account_name=? LIMIT 1");

		if ($prep_stmt9) {
			for my $accnt ( keys %pre_existing_accnts ) {
				my $rc = $prep_stmt9->execute(${$pre_existing_accnts{$accnt}}{"amount"}, ${$pre_existing_accnts{$accnt}}{"hmac"}, ${$pre_existing_accnts{$accnt}}{"account_name"});
				unless ($rc) {
					print STDERR "Couldn't execute UPDATE account_balances: ", $prep_stmt9->errstr, $/;
				}
			}
		}
		else {
			print STDERR "Couldn't prepare REPLACE INTO account_balances: ", $prep_stmt9->errstr, $/;
		}
	}

	#cancel any prepayments
	if ( scalar(keys %prepayment_write_offs) > 0 ) {
			
		my $prep_stmt8 = $con->prepare("SELECT receipt_no,paid_in_by,class,amount,mode_payment,ref_id,votehead,time,hmac FROM receipts WHERE paid_in_by=?");

		if ($prep_stmt8) {

			#read any negative arrears--expect only 1 result
			my $prep_stmt9 = $con->prepare("SELECT receipt_votehead,votehead,amount,time,hmac FROM cash_book WHERE receipt_votehead=? LIMIT 1");

			if ($prep_stmt9) {

				#overwrite current 
			
				my %receipts = ();
				my %edited_cash_book_entries = ();

				for my $adm ( keys %prepayment_write_offs ) {
					#print "X-Debug-4-$adm: proc'ng prepayment\r\n";
					my $encd_adm = $cipher->encrypt(add_padding($adm));
	
					my $rc = $prep_stmt8->execute($encd_adm);

					if ($rc) {

						while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

							my $receipt_no = $rslts[0];
							my $paid_in_by = remove_padding($cipher->decrypt($rslts[1]));
							my $class = remove_padding($cipher->decrypt($rslts[2]));
							my $amount = remove_padding($cipher->decrypt($rslts[3]));
							my $mode_payment = remove_padding($cipher->decrypt($rslts[4]));
							my $ref_id = remove_padding($cipher->decrypt($rslts[5]));
 							my $votehead = remove_padding($cipher->decrypt($rslts[6]));
							my $time = remove_padding($cipher->decrypt($rslts[7]));

							if ( $amount =~ /^\d{1,10}(\.\d{1,2})?$/ ) {

								my $hmac = uc(hmac_sha1_hex($paid_in_by . $class . $amount . $mode_payment . $ref_id . $votehead . $time, $key));

								if ( $hmac eq $rslts[8] ) {
									#record the time for sorting
									#print "X-Debug-$adm-$receipt_no: seen receipt for $amount\r\n";
									${$receipts{$adm}}{$receipt_no} = $time;
								}
							}	
						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM receipts: ", $prep_stmt8->errstr, $/;
					}
					#have I seen any receipts
					#perl is very quick to create hash keys
					#i use exists to avoid that here
					if ( exists $receipts{$adm} and scalar (keys %{$receipts{$adm}}) > 0 ) {

						my $prepayment_amnt = $prepayment_write_offs{$adm};
						#print "X-Debug-2-$adm: prepayment is $prepayment_amnt\r\n";

						#walk backwards through the receipts seen
						#the most relevant receipts are at the back
						JJ: for my $receipt ( sort {$receipts{$adm}->{$b} <=>  $receipts{$adm}->{$a}} keys %{$receipts{$adm}} ) {

							my $encd_receipt_votehead = $cipher->encrypt(add_padding($receipt . "-arrears"));
							my $rc = $prep_stmt9->execute($encd_receipt_votehead);

							if ( $rc ) {

								while ( my @rslts = $prep_stmt9->fetchrow_array() ) {

									my $receipt_votehead = remove_padding($cipher->decrypt($rslts[0]));
									my $votehead = remove_padding($cipher->decrypt($rslts[1]));
									my $amount = remove_padding($cipher->decrypt($rslts[2]));
									my $time = remove_padding($cipher->decrypt($rslts[3]));

									#amount must be negative i.e a prepayment
									if ( $amount =~ /^\-\d+(\.\d{1,2})?$/ ) {

										my $hmac = uc(hmac_sha1_hex($receipt_votehead . $votehead . $amount . $time, $key));
	
										if ( $hmac eq $rslts[4] ) {
											#print "X-Debug-3-$adm-$receipt_votehead: proc'ng amount of $amount\r\n";
											my $done = 0;
											#will this prepayment be cleared by this cash book entry?
											my $pre_amnt = $amount;
											if ( $prepayment_amnt <= ($amount * -1) ) {
												$amount += $prepayment_amnt;
												#break out--all debts have been settled
												$done++;
											}
											else {
												$prepayment_amnt -= ($amount * -1);
												$amount = 0;
											}
											
											my $n_hmac = uc(hmac_sha1_hex($receipt_votehead . $votehead . $amount . $time, $key));

											$edited_cash_book_entries{$receipt_votehead} = { "receipt_votehead" => $rslts[0], "votehead" => $rslts[1], "amount" => $cipher->encrypt(add_padding($amount)), "time" => $rslts[3], "hmac" => $n_hmac };
											#print "X-Debug-0-$n_hmac: updated amnt to $amount from $pre_amnt\r\n"; 
											if ($done) {
												last JJ;
											}
										}

									}
								}

							}
							else {
								print STDERR "Couldn't execute SELECT FROM cash_book: ", $prep_stmt9->errstr, $/;
							}
						}
					}
				}

				#commit any changes
				if ( scalar (keys %edited_cash_book_entries) > 0 ) {

					#print "X-Debug: updating prepayments\r\n";

					my $prep_stmt10 = $con->prepare("REPLACE INTO cash_book VALUES(?,?,?,?,?)");

					for my $receipt_votehead ( keys %edited_cash_book_entries ) {

						#print qq!X-Debug-$edited_cash_book_entries{$receipt_votehead}->{"hmac"}: updated amnt\r\n!;

						$prep_stmt10->execute($edited_cash_book_entries{$receipt_votehead}->{"receipt_votehead"}, $edited_cash_book_entries{$receipt_votehead}->{"votehead"}, $edited_cash_book_entries{$receipt_votehead}->{"amount"}, $edited_cash_book_entries{$receipt_votehead}->{"time"}, $edited_cash_book_entries{$receipt_votehead}->{"hmac"});

					}

				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM cash_book: ", $prep_stmt9->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM receipts: ", $prep_stmt8->errstr, $/;
		}
	}


	#record cash_book entrie
	if ( scalar(keys %cash_book_updates) > 0 ) {

		my $prep_stmt11 = $con->prepare("INSERT INTO cash_book VALUES(?,?,?,?,?)");
		if ( $prep_stmt11 ) {
			for my $accnt (keys %cash_book_updates) {
				my $rc = $prep_stmt11->execute($cash_book_updates{$accnt}->{"receipt_votehead"}, $cash_book_updates{$accnt}->{"votehead"}, $cash_book_updates{$accnt}->{"amount"}, $cash_book_updates{$accnt}->{"time"}, $cash_book_updates{$accnt}->{"hmac"});
				unless ($rc) {
					print STDERR "Couldn't execute INSERT INTO cash_book: ", $prep_stmt11->errstr, $/;				
				}
			}
		}
		else {
			print STDERR "Couldn't prepare INSERT INTO cash_book: ", $prep_stmt11->errstr, $/;
		}

	}

	#record payments_book entries
	if ( scalar(keys %payments_book_updates) > 0 ) {

		my $prep_stmt12 = $con->prepare("INSERT INTO payments_book VALUES(?,?,?,?,?)");
		if ($prep_stmt12) {
			for my $accnt (keys %payments_book_updates) {
				my $rc = $prep_stmt12->execute($payments_book_updates{$accnt}->{"voucher_votehead"}, $payments_book_updates{$accnt}->{"votehead"}, $payments_book_updates{$accnt}->{"amount"}, $payments_book_updates{$accnt}->{"time"}, $payments_book_updates{$accnt}->{"hmac"});
				unless ($rc) {
					print STDERR "Couldn't execute INSERT INTO payments_book: ", $prep_stmt12->errstr, $/;
				}
			}
		}
		else {
			print STDERR "Couldn't prepare INSERT INTO cash_book: ", $prep_stmt12->errstr, $/;
		}

	}

	my $update_total = 0;
	
	my $prep_stmt10 = $con->prepare("INSERT INTO account_balance_updates VALUES(?,?,?,?)");

	#log update
	my @today = localtime($time);	
	my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       	if ($log_f) {

		my $time_f = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
		flock ($log_f, LOCK_EX) or print STDERR "Could not log update balances for $id due to flock error: $!$/";
		seek ($log_f, 0, SEEK_END);

		for my $votehead_1 (keys %voteheads) {

			$update_total += $voteheads{$votehead_1};

			my $encd_amount = $cipher->encrypt(add_padding($voteheads{$votehead_1}));

			for my $adm (keys %adms) {

				my $encd_accnt_name = $cipher->encrypt(add_padding($adm . "-" . $votehead_1));			
			

				my $hmac =  uc(hmac_sha1_hex($adm . "-" . $votehead_1 . $voteheads{$votehead_1} . $time, $key));
			
				my $rc = $prep_stmt10->execute($encd_accnt_name, $encd_amount, $encd_time, $hmac);

				if ($rc) {
					my $f_votehead = ucfirst($votehead_1);
					print $log_f qq!$id UPDATE BALANCES $adm $f_votehead($voteheads{$votehead_1}) $time_f\n!;
				}
			}
		}

		flock ($log_f, LOCK_UN);
               	close $log_f;

	}
	else {
		print STDERR "Could not log view balances $id: $!\n";
	}

	my $incr_decr = "incremented";

	if ( $update_total < 0 ) {
		$incr_decr = "decremented";
		$update_total *= -1;
	}

	$update_total = format_currency($update_total);

	my $stud_list = "";

	for my $adm_3 ( keys %adms ) {
		$stud_list .= qq!<TR><TD>$adm_3<TD>${$adms{$adm_3}}{"name"}<TD>${$adms{$adm_3}}{"class"}!;
	}

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Update Fee Balances</title>
</head>
<body>
$header
<p>The following student(s) fee balances were <span style="font-weight: bold">$incr_decr by $update_total</span>:

<TABLE>

<THEAD>
<TH>Adm No.<TH>Name<TH>Class
</THEAD>
<TBODY>
$stud_list
</TBODY>
</TABLE>
</body>
</html>
*;
	$con->commit();
}
}

if (not $post_mode) {

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my $current_yr = (localtime)[5] + 1900; 

	my %grouped_classes = ("1"=> "1", "2"=> "2", "3"=> "3","4"=> "4");
	
	my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='1-classes' LIMIT 1");

	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {
				my @classes = split/,/, $rslts[0];
				%grouped_classes = ();
				for my $class (@classes) {
					if ($class =~ /(\d+)/) {	
						$grouped_classes{$1}->{$class}++;
					}
				}
			}
		}
	}

	my %class_table_lookup = ();
	#my %table_class_lookup = ();

	my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls WHERE grad_year >= ?");

	if ($prep_stmt1) {

		my $rc = $prep_stmt1->execute($current_yr);
		if ($rc) {	
			while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

				my $class = $rslts[1];
				my $class_yr = ($current_yr - $rslts[2]) + 1;
				
				$class =~ s/\d+/$class_yr/;

				$class_table_lookup{lc($class)} = $rslts[0];
				#$table_class_lookup{$rslts[0]} = $class;

			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
	}


	my $classes_select = qq!<DIV id="classes_select"><TABLE cellpadding="5%" cellspacing="5%"><TR>!;
	my $classes_select_2 = qq!<SELECT id="new_student_class_select" onchange="check_new_student_class()" disabled="1">!;

	for my $class_yr (sort {$a <=> $b} keys %grouped_classes) {

		my @classes = keys %{$grouped_classes{$class_yr}};
		
		$classes_select .= "<TD>";	

		for my $class (sort {$a cmp $b} @classes) {
	
			my $roll = "";
			if (exists $class_table_lookup{lc($class)}) {
				$roll = $class_table_lookup{lc($class)};
			}

			$classes_select .= qq{<INPUT type="checkbox" name="class_$class" value="$class" id="class_$class" onclick="disable_adm('class_$class')"><LABEL for="class_$class">$class</LABEL><BR>};
			$classes_select_2 .= qq{<OPTION value="$roll" title="$class">$class</OPTION>};
		}
	}


	$classes_select .= qq!<TD style="vertical-align: center; border-left: solid"><LABEL for="year">Year</LABEL>&nbsp;<INPUT type="text" size="4" maxlength="4" name="year" value="$current_yr"></TABLE></DIV>!;
	$classes_select_2 .= "</SELECT>";

	my %votehead_amounts = ();
	my %votehead_amounts_exceptions = ();

	my %ordered_fee_structure = ();

	#read fee structure
	my $prep_stmt2 = $con->prepare("SELECT votehead_index,votehead_name,class,amount,hmac FROM fee_structure");
	
	if ($prep_stmt2) {
	
		my $rc = $prep_stmt2->execute();
		if ($rc) {
			while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
					
				my $decrypted_votehead_index = $cipher->decrypt($rslts[0]);
				my $decrypted_votehead_name = $cipher->decrypt($rslts[1]);
				my $decrypted_class = $cipher->decrypt($rslts[2]);
				my $decrypted_amount = $cipher->decrypt($rslts[3]);

				my $votehead_index = remove_padding($decrypted_votehead_index);
				my $votehead_name = remove_padding($decrypted_votehead_name);
				my $class = remove_padding($decrypted_class);
				my $amount = remove_padding($decrypted_amount);
	
				#valid decryption
				if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($votehead_index . $votehead_name . $class . $amount, $key));
								
					#auth the data
					if ( $hmac eq $rslts[4] ) {	
						$ordered_fee_structure{lc($votehead_name)} = {"index" => $votehead_index, "name" => $votehead_name};
						#root votehead amounts
						if ($class eq "") {
							$votehead_amounts{$votehead_name} = $amount;
						}
						else {
							$votehead_amounts_exceptions{$class}->{$votehead_name} = $amount;
						}
					}
				}
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
	}

	my $voteheads_amounts = qq!<TABLE cellspacing="5%">!;

	foreach (sort { $ordered_fee_structure{$a}->{"index"} <=> $ordered_fee_structure{$b}->{"index"}} keys %ordered_fee_structure) {

		$voteheads_amounts .= qq!<TR><TD><span style="color: red" id="${_}_err"></span><LABEL for="$_">$ordered_fee_structure{$_}->{"name"}</LABEL><TD><INPUT type="text" name="votehead_$_" value="" id="$_" size="12" maxlength="12" onkeyup="check_amount('$_')" onmousemove="check_amount('$_')" autocomplete="off"><TR style="font-style: italic"><TD>&nbsp;<TD><span id="${_}_in_words"></span>!;

	}

	$voteheads_amounts .= "</TABLE>";

	my @votehead_amounts_bts = ();

	for my $votehead (keys %votehead_amounts) {
		push @votehead_amounts_bts, qq!"$votehead": $votehead_amounts{$votehead}!;
	}

	my $json_votehead_amounts = "{" . join(", ", @votehead_amounts_bts) . "}";	

	my @votehead_exceptions = ();

	for my $roll (keys %votehead_amounts_exceptions) {

		my @roll_votehead_amounts_bts = (qq!class: "$roll"!);
		for my $votehead ( keys %{$votehead_amounts_exceptions{$roll}} ) {
			push @roll_votehead_amounts_bts, qq!"$votehead": $votehead_amounts_exceptions{$roll}->{$votehead}!;
		}

		push @votehead_exceptions, "{" . join(", ", @roll_votehead_amounts_bts) . "}";

	}

	my $json_votehead_exceptions = "[" . join(", ", @votehead_exceptions) . "]"; 

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Update Fee Balances</title>

<script type="text/javascript">

var num_re = /^[\-\+]?([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;
var left_padded_num = /^0+([^0]+.?\$)/;
var adm_no_re = /^([0-9]\*(\\-[0-9]\*)?\\s\*)\*\$/;
var num_checked = 0;
var votehead_amounts = $json_votehead_amounts;
var votehead_exceptions = $json_votehead_exceptions;

function check_new_student() {

	var is_new_student = document.getElementById("new_student").checked;
	if (is_new_student) {
		document.getElementById("new_student_class_container").style.color = "";
		document.getElementById("new_student_class_select").disabled = false;
		check_new_student_class();
	}
	else {
		document.getElementById("new_student_class_container").style.color = "gray";
		document.getElementById("new_student_class_select").disabled = true;
	}

}

function check_new_student_class() {
	var selected_class = document.getElementById("new_student_class_select").value;
	for (votehead in votehead_amounts) {
		document.getElementById(votehead.toLowerCase()).value = votehead_amounts[votehead];
	}
	for (var i = 0; i < votehead_exceptions.length; i++) {
		if (votehead_exceptions[i].class == selected_class) {
			for (votehead in votehead_exceptions[i]) {
				if (votehead == "class") {
					continue;
				}
				document.getElementById(votehead.toLowerCase()).value = votehead_exceptions[i][votehead];
			}
			break;
		}
	}
}

function check_adm_nos() {

	var adm_numbers = document.getElementById("adm_nos").value;
	if (adm_numbers.match(adm_no_re)) {
		document.getElementById("classes_select").style.color = "gray";
		document.getElementById("adm_nos_err").innerHTML = "";
	}
	else {
		document.getElementById("classes_select").style.color = "";
		document.getElementById("adm_nos_err").innerHTML = "\*";
	}
}

function disable_adm(checkbox) {

	if (document.getElementById(checkbox).checked) {
		num_checked++;
	}
	else {
		num_checked--;
	}

	if (num_checked > 0) {
		document.getElementById("adm_nos").disabled = true;
		document.getElementById("adm_nos").value = "";
		document.getElementById("new_student_container").style.color = "gray";
		document.getElementById("adm_nos_container").style.color = "gray";
		document.getElementById("new_student").disabled = true;
	}
	else if (num_checked <= 0) {
		num_checked = 0;
		document.getElementById("adm_nos").disabled = false;
		document.getElementById("new_student_container").style.color = "";
		document.getElementById("adm_nos_container").style.color = "";
		document.getElementById("new_student").disabled = false;
	}
}

function check_amount(prefix) {

	var amnt = document.getElementById(prefix).value;
	var match_groups = amnt.match(num_re);

	if ( match_groups ) {

		var shs = match_groups[1];
		var cents = match_groups[3];

		var unpadded_shs = shs.match(left_padded_num);
		if (unpadded_shs) {
			shs = unpadded_shs[1];
		}

		var shs_words = "";

		var shs_digits = shs.split("");
		var last_elem = (shs_digits.length) - 1;

		var tens_words = "";
		var hundreds_words = "";
		var thousands_words = "";
		var hundred_thousand_words = "";
		var millions_words = "";
		var hundred_million_words = "";
		var billions_words = "";

		var blank_millions = true;
		var blank_thousands = true;
		var blank_tens = true;

		if (last_elem > 0) {

			var tens = (shs_digits[last_elem - 1 ] + "" + shs_digits[last_elem]);	

			if (parseInt(tens) > 0) {
				blank_tens = false;

				if (parseInt(tens) < 10) {	
					var left_padding = tens.match(left_padded_num);
					if (left_padding) {
						tens = left_padding[1];
					}
						
					tens_words = get_num_in_words_ones(tens);
				}
				else if(parseInt(tens) < 20) {				
					tens_words = get_num_in_words_teens(tens)
				}
				else {	
					var ones = get_num_in_words_ones(shs_digits[last_elem]);
					var tens = get_num_in_words_tens(shs_digits[last_elem-1]);
	
					tens_words = tens + " " + ones;
				}

			}

			if (last_elem > 1) {

				var hundreds = get_num_in_words_ones(shs_digits[last_elem-2]);
				if (hundreds.length > 0) {
					hundreds_words = hundreds + " hundred ";
				}

				if (last_elem > 2) {

					var thousands = shs_digits[last_elem - 3];

					if (last_elem > 3) {
						thousands = shs_digits[last_elem - 4] + "" + thousands;
					}

					
					//alert("thousands: " + thousands + ".");
					if (parseInt(thousands) > 0) {
						blank_thousands = false;
						if (parseInt(thousands) < 10) {
	
							var left_padding = thousands.match(left_padded_num);
							if (left_padding) {
								thousands = left_padding[1];
							}
							thousands_words = get_num_in_words_ones(thousands) + " thousand";
						}
						else if (parseInt(thousands) < 20) {	
							thousands_words = get_num_in_words_teens(thousands) + " thousand";
						}
						else if (parseInt(thousands) >= 20) {	
						
							var ones = get_num_in_words_ones(shs_digits[last_elem - 3]);
							var tens = get_num_in_words_tens(shs_digits[last_elem - 4]);
	
							thousands_words = tens + " " + ones + " thousand";	
						}

					}
					if (last_elem > 4) {	
						var hundred_thousand = get_num_in_words_ones(shs_digits[last_elem-5]);	
						if ( hundred_thousand.length > 0 ) {
							hundred_thousand_words = hundred_thousand + " hundred";
						}
					}

					if (last_elem > 5) {

						var millions = shs_digits[last_elem - 6];

						if ( last_elem > 6 ) {
							millions = shs_digits[last_elem - 7] + "" + millions;
						}

						if (parseInt(millions) > 0) {

							blank_millions = false;

							if (parseInt(millions) < 10) {					
								var left_padding = millions.match(left_padded_num);
								if (left_padding) {
									millions = left_padding[1];
								}
								millions_words = get_num_in_words_ones(millions)  + " million";
							}
							else if (parseInt(millions) < 20) {
				
								millions_words = get_num_in_words_teens(millions) + " million";
							}
							else {
					
								var ones = get_num_in_words_ones(shs_digits[last_elem - 6]);
								var tens = get_num_in_words_tens(shs_digits[last_elem - 7]);
	
								millions_words = tens + " " + ones + " million";
							}
						}
					}

					if (last_elem > 7) {
						var hundred_million = get_num_in_words_ones(shs_digits[last_elem - 8]);
						if  ( hundred_million.length > 0 ) {
							hundred_million_words = hundred_million + " hundred";
						}

						if (last_elem > 8) {
							var billions = get_num_in_words_ones(shs_digits[last_elem - 9]);
							if (billions.length > 0) {
								billions_words = billions + " billion";
							}
						}
					}
				}
			}
			var preceding_values = 0;

			if (billions_words.length > 0) {
				shs_words += billions_words;
				preceding_values++;
			}
			if (hundred_million_words.length > 0) {
				if (preceding_values) {
					shs_words += ", ";
				}

				shs_words += hundred_million_words;
				if (blank_millions) {
					shs_words += " million";
				}
				preceding_values++;
			}
			if (millions_words.length > 0) {
				if ( preceding_values && \!blank_millions ) {
					shs_words += " and ";
				}
				shs_words += millions_words;
				preceding_values++;
			}
			if ( hundred_thousand_words.length > 0 ) {
				if (preceding_values) {
					shs_words += ", ";
				}
				shs_words += hundred_thousand_words;
				if (blank_thousands) {
					shs_words += " thousand";
				}
				preceding_values++;
			}
			if (thousands_words.length > 0) {	
				if (preceding_values && \!blank_thousands) {
					shs_words += " and ";
				}
				shs_words += thousands_words;
				preceding_values++;
			}
			if (hundreds_words.length > 0) {
				if ( preceding_values) {
					shs_words += ", ";
				}
				preceding_values++;
				shs_words += hundreds_words;
			}
			if (tens_words.length > 0) {
				if (preceding_values && \!blank_tens) {
					shs_words += " and ";
				}
				shs_words += tens_words;
			}
			shs_words += " shillings";
		}
		else {
			shs_words = get_num_in_words_ones(shs_digits[0]) + " shillings";
		}
		
		var amnt_words = shs_words;	

		if (cents \!= null) {
			var unpadded_cents = cents.match(left_padded_num);
			if ( unpadded_cents ) {
				cents = unpadded_cents[1]; 
			}
			var cents_words = "";
			if (cents < 10) {
				cents_words = get_num_in_words_ones(cents);
			}
			else if (cents < 20) {
				cents_words = get_num_in_words_teens(cents);
			}
			else {	
				var cents_bts = cents.split("");

				var ones = get_num_in_words_ones(cents_bts[1]);
				var tens = get_num_in_words_tens(cents_bts[0]);
	
				cents_words = tens + " " + ones;
			}
			amnt_words += " and " + cents_words + " cents";
		}
	
		amnt_words += ".";

		var first_char = amnt_words.substr(0,1);
		var uc_first_char = first_char.toUpperCase();

		var rest_str = amnt_words.substr(1);
		amnt_words = uc_first_char + rest_str;	

		document.getElementById(prefix + "_in_words").innerHTML = amnt_words;
		document.getElementById(prefix + "_err").innerHTML = "";

	}
	else {
		document.getElementById(prefix + "_err").innerHTML = "\*";
		document.getElementById(prefix + "_in_words").innerHTML = "";
	}

}

function get_num_in_words_ones(num) {
	switch (num) {
		case "0":
			return "";
		case "1":
			return "one";
		case "2":
			return "two";
		case "3":
			return "three";
		case "4":
			return "four";
		case "5":
			return "five";
		case "6":
			return "six";
		case "7":
			return "seven";
		case "8":
			return "eight";
		case "9":
			return "nine";
	}
	return "";
}

function get_num_in_words_teens(num) {
	switch (num) {
		case "10":
			return "ten";
		case "11":
			return "eleven";
		case "12":
			return "twelve";
		case "13":
			return "thirteen";
		case "14":
			return "fourteen";
		case "15":
			return "fifteen";
		case "16":
			return "sixteen";
		case "17":
			return "seventeen";
		case "18":
			return "eighteen";
		case "19":
			return "nineteen";
	}
	return "";
}

function get_num_in_words_tens(num) {
	switch (num) {	
		case "2":
			return "twenty";
		case "3":
			return "thirty";
		case "4":
			return "forty";
		case "5":
			return "fifty";
		case "6":
			return "sixty";
		case "7":
			return "seventy";
		case "8":
			return "eighty";
		case "9":
			return "ninety";
	}
	return "";
}

</script>

</head>

<body>
$header
$feedback
<form method="POST" action="/cgi-bin/fee_update.cgi">
<input type="hidden" name="confirm_code" value="$conf_code">
<p><h3>Filter Students By</h3>

<ul style="list-style-type: none">
<li><h4>Adm No.</h4>
<span id="adm_nos_err" style="color: red"></span><span id="adm_nos_container"><label for="adm_no">Adm no(s)</label>&nbsp;<input type="text" size="50" name="adm_nos" id="adm_nos" onkeyup="check_adm_nos()">&nbsp;&nbsp;<em>You can include ranges like 4490-4500</em></span>
<br><span id="new_student_container"><label for="">Is this a new student?</label>&nbsp;<input type="checkbox" id="new_student" onclick="check_new_student()"></span>
<br><span id="new_student_class_container" style="color: gray"><label for="">Class</label>&nbsp;$classes_select_2</span>
<li><h4>or; Class</h4>
$classes_select
</ul>

<p><h3>Voteheads to Update</h3>
<p><em>You can specify a negative number to reduce a student's balance.
<p>
$voteheads_amounts
<table>
<tr>
<td><input type="submit" name="save" value="Save">
</table>
</form>

</body>

</html>
*;

}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;

}
